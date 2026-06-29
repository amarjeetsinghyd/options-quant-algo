import threading
import time
from datetime import datetime
import sqlite3
import uuid
import json
import queue
import os
import sys
import pandas as pd

from src.core.market_calendar import MarketCalendar
from src.ml_engine.feature_builder import extract_features
from src.ml_engine.data_validator import DataValidator
from src.utils.logger import get_logger
from src.utils.instrumentation import get_db_connection
from src.config.engineering_config import ML_DB_PATH as DB_PATH
from src.core.db_writer_queue import DBWriterQueue

logger = get_logger("gamma_event_collector")


class GammaEventCollector:
    MAX_TRACKING_SYMBOLS = 100
    MAX_HISTORY_SECONDS = 300
    COOLDOWN_SECONDS = 60
    TRACKING_HORIZON_SECONDS = 180

    def __init__(self):
        self.tracking_window = {}      # {symbol: [(timestamp, price, index_price, market_state_copy, option_details_copy)]}
        self.last_tick_time = {}       # {symbol: timestamp} (LRU tracking)
        self.cooldowns = {}            # {symbol: timestamp}
        self.active_sessions = {}      # {symbol: session_dict}
        self.lock = threading.Lock()
        
        # Thread-safe queue for database writes and background processing
        self.event_queue = queue.Queue()
        
        # Start background worker thread
        self.worker_thread = threading.Thread(target=self._db_worker, daemon=True)
        self.worker_thread.start()
        logger.info("Background DB Worker Thread initialized.")

    def _get_db_conn(self):
        return get_db_connection(DB_PATH)

    def feed_tick(self, symbol, price, index_price, market_state, option_details, exchange_timestamp=None):
        """
        Receives real-time snapquotes from WebSocket.
        Uses LRU eviction to stay under MAX_TRACKING_SYMBOLS.
        Processes ticks for active event sessions and scans for new ignitions.
        """
        now = time.time()
        
        # Standardize exchange timestamp and calculate latency
        def format_ts(ts):
            if not ts:
                return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                if isinstance(ts, (int, float)):
                    if ts > 1e11:
                        ts = ts / 1000.0
                    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(ts, str):
                    return pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(ts, datetime):
                    return ts.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    return str(ts)
            except Exception:
                return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        exch_ts_str = format_ts(exchange_timestamp)
        local_ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            local_dt = datetime.strptime(local_ts_str, "%Y-%m-%d %H:%M:%S")
            exch_dt = datetime.strptime(exch_ts_str, "%Y-%m-%d %H:%M:%S")
            tick_latency = (local_dt - exch_dt).total_seconds() * 1000.0
        except Exception:
            tick_latency = 0.0

        with self.lock:
            # 1. LRU Eviction Check
            if symbol not in self.tracking_window:
                if len(self.tracking_window) >= self.MAX_TRACKING_SYMBOLS:
                    # Find and evict oldest symbol
                    oldest_sym = min(self.last_tick_time, key=self.last_tick_time.get)
                    self.tracking_window.pop(oldest_sym, None)
                    self.last_tick_time.pop(oldest_sym, None)
                    self.cooldowns.pop(oldest_sym, None)
                    self.active_sessions.pop(oldest_sym, None)
                self.tracking_window[symbol] = []
            
            self.last_tick_time[symbol] = now
            
            # Deep copy state dictionaries to prevent modification by main thread
            market_state_copy = json.loads(json.dumps(market_state)) if market_state else {}
            option_details_copy = json.loads(json.dumps(option_details)) if option_details else {}
            
            # Append tick data with 8 elements
            self.tracking_window[symbol].append((now, price, index_price, market_state_copy, option_details_copy, tick_latency, exch_ts_str, local_ts_str))
            
            # Prune ticks older than MAX_HISTORY_SECONDS
            self.tracking_window[symbol] = [
                tick for tick in self.tracking_window[symbol] if now - tick[0] <= self.MAX_HISTORY_SECONDS
            ]
            
            ticks = self.tracking_window[symbol]
            if len(ticks) < 2:
                return

            # 2. Check Cooldown
            cooldown_until = self.cooldowns.get(symbol, 0)
            if now < cooldown_until:
                # If in cooldown but we have an active session, continue recording path
                if symbol in self.active_sessions:
                    self._update_active_session(symbol, now, price, index_price, market_state_copy, option_details_copy, tick_latency, exch_ts_str, local_ts_str)
                return

            # 3. Handle Active Session
            if symbol in self.active_sessions:
                self._update_active_session(symbol, now, price, index_price, market_state_copy, option_details_copy, tick_latency, exch_ts_str, local_ts_str)
            else:
                # 4. Scan for New Ignition
                # Verify session type is LIVE/SIMULATION/REPLAY/UNIT_TEST before creating a new session
                session_type = MarketCalendar.get_session_type()
                if "unittest" in sys.modules or any("test" in arg.lower() for arg in sys.argv):
                    session_type = "UNIT_TEST"
                if session_type not in {"LIVE", "SIMULATION", "REPLAY", "UNIT_TEST"}:
                    # Block new session creation outside active hours
                    return

                # Find min price in the window that occurred before the current price
                min_price = float('inf')
                min_tick = None
                
                for tick in ticks[:-1]:
                    t_time, t_price, t_idx_p, _, _ = tick[0], tick[1], tick[2], tick[3], tick[4]
                    if t_price < min_price and t_price > 0:
                        min_price = t_price
                        min_tick = tick
                
                if min_tick and min_price > 0:
                    pct_move = ((price - min_price) / min_price) * 100
                    
                    if pct_move >= 5.0: # 5% trigger threshold
                        t_min = min_tick[0]
                        t_min_m_state = min_tick[3]
                        
                        # Initialize Event Session
                        self.active_sessions[symbol] = {
                            "event_id": str(uuid.uuid4()),
                            "symbol": symbol,
                            "start_time": t_min,
                            "start_price": min_price,
                            "detection_time": now,
                            "detection_price": price,
                            "max_price": price,
                            "max_price_time": now,
                            "option_details": option_details_copy,
                            "pre_market_state": t_min_m_state,
                            "ticks": [t for t in ticks if t[0] >= t_min]
                        }
                        
                        # Set Cooldown
                        self.cooldowns[symbol] = now + self.COOLDOWN_SECONDS

    def _update_active_session(self, symbol, timestamp, price, index_price, market_state, option_details, tick_latency, exch_ts, local_ts):
        session = self.active_sessions[symbol]
        session["ticks"].append((timestamp, price, index_price, market_state, option_details, tick_latency, exch_ts, local_ts))
        
        if price > session["max_price"]:
            session["max_price"] = price
            session["max_price_time"] = timestamp
            
        # Check if tracking horizon completed (180s)
        if timestamp - session["detection_time"] >= self.TRACKING_HORIZON_SECONDS:
            # Finalize and Queue for background DB logging
            self.event_queue.put(session)
            self.active_sessions.pop(symbol, None)
            
            # Trigger sampling of 3 negative (Quality 0) events to maintain 1:3 ratio
            self._trigger_negative_sampling(timestamp)

    def _trigger_negative_sampling(self, timestamp):
        """Finds low volatility options in the tracking window and logs them as Quality 0 (Dead moves)."""
        sampled_count = 0
        
        for sym, ticks in self.tracking_window.items():
            if sampled_count >= 3:
                break
                
            if sym in self.active_sessions or sym in self.cooldowns:
                continue
                
            if len(ticks) < 10:
                continue
                
            prices = [t[1] for t in ticks]
            p_min = min(prices)
            p_max = max(prices)
            
            if p_min > 0:
                max_variance = ((p_max - p_min) / p_min) * 100
                if max_variance < 3.0: # Very low volatility
                    # Create Quality 0 Session
                    q0_session = {
                        "event_id": str(uuid.uuid4()),
                        "symbol": sym,
                        "start_time": ticks[0][0],
                        "start_price": ticks[0][1],
                        "detection_time": timestamp,
                        "detection_price": ticks[-1][1],
                        "max_price": p_max,
                        "max_price_time": timestamp,
                        "option_details": ticks[0][4],
                        "pre_market_state": ticks[0][3],
                        "ticks": ticks,
                        "is_quality_0": True
                    }
                    self.event_queue.put(q0_session)
                    sampled_count += 1

    def _db_worker(self):
        """Worker running in a background thread to calculate features, run validation, and write to SQLite."""
        while True:
            try:
                session = self.event_queue.get()
                if session is None:
                    break
                    
                self._process_and_log_event(session)
                self.event_queue.task_done()
            except Exception as e:
                logger.error(f"Error processing queued event: {e}")
                time.sleep(1)

    def _process_and_log_event(self, session):
        symbol = session["symbol"]
        ticks = session["ticks"]
        is_quality_0 = session.get("is_quality_0", False)
        
        t_start = session["start_time"]
        p_start = session["start_price"]
        p_max = session["max_price"]
        p_end = ticks[-1][1]
        
        # Calculate moves
        max_attempted_move = ((p_max - p_start) / p_start) * 100 if p_start > 0 else 0.0
        rejection_after_move = ((p_max - p_end) / p_max) * 100 if p_max > 0 else 0.0
        
        # 1. Determine Quality
        # Classifications:
        # Quality 0: Dead move
        # Quality 1: Ignition attempt but failed (retraced > 70% or below starting price)
        # Quality 2: Small gamma (5-10% and held)
        # Quality 3: Clean gamma (10-20% and held)
        # Quality 4: Explosive gamma (>= 20% and held)
        
        failure_reason = None
        if is_quality_0:
            quality = 0
            failure_reason = "DEAD_MOVE"
        else:
            # Retracement threshold check (crashed back below 30% of peak gain or below entry)
            retrace_pct = (p_max - p_end) / (p_max - p_start) if p_max > p_start else 0.0
            
            if retrace_pct > 0.70 or p_end < p_start:
                quality = 1
                failure_reason = "RETRACEMENT_EXCEEDED"
            elif max_attempted_move >= 20.0:
                quality = 4
            elif max_attempted_move >= 10.0:
                quality = 3
            else:
                quality = 2

        # 2. Build Replay Path Lists
        timestamp_sequence = [datetime.fromtimestamp(t[0]).strftime("%Y-%m-%d %H:%M:%S") for t in ticks]
        premium_path = [t[1] for t in ticks]
        underlying_path = [t[2] for t in ticks]
        
        # 3. Calculate Feature Evolution & Snapshot Versioning
        feature_evolution = []
        pre_event_snapshot = None
        post_event_snapshot = None
        
        # We construct features for every tick step to support replay later
        for tick in ticks:
            t_time, t_price, t_idx_p, t_m_state, t_opt_details = tick[0], tick[1], tick[2], tick[3], tick[4]
            # Format option data for feature builder
            t_opt_data = {
                "premium": t_price,
                "dte": t_opt_details.get("dte", 0),
                "expiry": t_opt_details.get("expiry"),
                "distance": t_opt_details.get("distance", 0.0)
            }
            t_signal = {"option_data": t_opt_data}
            t_state = {"market_state": t_m_state}
            
            # Feed rolling ticks to feature builder velocity
            rolling_ticks = [(tk[0], tk[1]) for tk in ticks if tk[0] <= t_time]
            
            feat = extract_features(t_state, t_signal, premium_history=rolling_ticks)
            feature_evolution.append(feat)
            
        if feature_evolution:
            pre_event_snapshot = json.dumps(feature_evolution[0])
            post_event_snapshot = json.dumps(feature_evolution[-1])
            
        # 4. Check Data Quality Gate
        # Validate pre-event features to check if tick is bad tick, low liquidity, etc.
        first_features = feature_evolution[0] if feature_evolution else {}
        is_valid, validation_reason = DataValidator.validate_sample(first_features, session["event_id"], symbol)
        if not is_valid:
            logger.warning(f"Dropped event {session['event_id'][:8]} due to Quality Check: {validation_reason}", extra={"event_id": session['event_id']})
            return # Dropped immediately

        # 5. Calculate data governance columns
        local_ts = datetime.fromtimestamp(session["detection_time"]).strftime("%Y-%m-%d %H:%M:%S")
        
        session_time = datetime.fromtimestamp(session["detection_time"])
        session_type = MarketCalendar.get_session_type(session_time)
        if "unittest" in sys.modules or any("test" in arg.lower() for arg in sys.argv):
            session_type = "UNIT_TEST"
            
        if session_type == "LIVE":
            data_source = "LIVE_WEBSOCKET"
        elif session_type == "REPLAY":
            data_source = "REPLAY_ENGINE"
        elif session_type == "SIMULATION":
            data_source = "SIMULATION"
        elif session_type == "UNIT_TEST":
            data_source = "UNIT_TEST"
        else:
            data_source = "UNKNOWN"

        gaps = []
        duplicate_ticks = 0
        latency_spikes = 0
        large_gaps = 0
        total_ticks = len(ticks)
        
        for i in range(1, len(ticks)):
            gap = ticks[i][0] - ticks[i-1][0]
            gaps.append(gap)
            if gap <= 0.001:
                duplicate_ticks += 1
            elif gap > 5.0:
                large_gaps += 1
                
            tick_latency = ticks[i][5] if len(ticks[i]) > 5 else 0.0
            if tick_latency > 2000.0:
                latency_spikes += 1
                
        if large_gaps >= 3 or total_ticks < 5:
            conn_quality = "POOR"
        elif large_gaps >= 1 or latency_spikes >= 3:
            conn_quality = "DEGRADED"
        else:
            conn_quality = "GOOD"
            
        q_score = 100.0
        if conn_quality == "DEGRADED":
            q_score -= 20.0
        elif conn_quality == "POOR":
            q_score -= 50.0
            
        if duplicate_ticks > 0:
            q_score -= 10.0
        if large_gaps > 0:
            q_score -= 15.0
        if latency_spikes > 0:
            q_score -= 10.0
            
        q_score = max(0.0, min(100.0, q_score))
        latency_ms = ticks[-1][5] if len(ticks[-1]) > 5 else 0.0
        exch_ts = ticks[-1][6] if len(ticks[-1]) > 6 else local_ts

        # 6. DB Write
        table = "gamma_events" if quality > 0 else "non_gamma_events"
        
        try:
            sql = f"""
                INSERT INTO {table} (
                        event_id, timestamp, index_name, option_symbol, strike, 
                        distance_from_atm, premium_before, premium_after, 
                        percentage_move, time_taken_seconds, dte, 
                        market_conditions_before_event, discovery_source, gamma_quality,
                        pre_event_snapshot, post_event_snapshot, gamma_timeframe,
                        max_attempted_move, rejection_after_move, failure_reason,
                        feature_engine_version, collector_version, calculation_version,
                        timestamp_sequence, premium_path, underlying_path, feature_evolution,
                        liquidity_score, spread_before_event,
                        session_type, data_source, quality_score, connection_quality,
                        observation_status, observation_version, exchange_timestamp,
                        local_timestamp, latency_ms, market_state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            params = (
                session["event_id"],
                local_ts,
                session["option_details"].get("index_name", "UNKNOWN"),
                symbol,
                session["option_details"].get("strike", 0.0),
                session["option_details"].get("distance", 0),
                p_start,
                p_end,
                ((p_end - p_start) / p_start * 100) if p_start > 0 else 0.0,
                int(session["detection_time"] - t_start),
                session["option_details"].get("dte", 0),
                json.dumps(session["pre_market_state"]),
                "BACKGROUND_COLLECTOR",
                quality,
                pre_event_snapshot,
                post_event_snapshot,
                int(session["detection_time"] - t_start), # gamma timeframe
                max_attempted_move,
                rejection_after_move,
                failure_reason,
                first_features.get("meta_versions", {}).get("market_regime", "v1"),
                "v5.2", # collector_version
                "v5.2", # calculation_version
                json.dumps(timestamp_sequence),
                json.dumps(premium_path),
                json.dumps(underlying_path),
                json.dumps(feature_evolution),
                first_features.get("ofa_score", 0.0), # liquidity_score proxy
                session["option_details"].get("spread", 0.0), # spread_before_event
                session_type,
                data_source,
                q_score,
                conn_quality,
                "FINALIZED",
                "v5.2",
                exch_ts,
                local_ts,
                latency_ms,
                "NORMAL"
            )
            DBWriterQueue.get_instance(DB_PATH).enqueue(sql, params)
            logger.info(f"Successfully queued Quality {quality} event for {symbol} to {table} table. ID: {session['event_id'][:8]}...", extra={"event_id": session['event_id'], "latency_ms": latency_ms, "database_name": "ml_research.db"})
        except Exception as e:
            logger.error(f"Queue Insert Error: {e}", extra={"database_name": "ml_research.db"})
