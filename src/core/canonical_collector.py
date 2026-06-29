import os
import time
import threading
import uuid
import platform
import pandas as pd
from datetime import datetime
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from src.utils.logger import get_logger
from src.config.engineering_config import DATA_DIR
from src.core.symbol_registry import SymbolRegistry
from src.core.message_bus import MessageBusSubscriber, FEED_PORT
from src.core.dataset_manifest import DatasetManifest
from src.core.market_calendar import MarketCalendar

logger = get_logger("canonical_collector")

# Base Data Lake Paths
INSTITUTIONAL_MEMORY = Path("data/institutional_memory")
RAW_TICKS_DIR = INSTITUTIONAL_MEMORY / "raw_ticks"
CANONICAL_DIR = INSTITUTIONAL_MEMORY / "canonical_observations"

class CanonicalCollector:
    """
    Canonical Observation Dataset v3.1 (Frozen)
    Implements the institutional permanent memory.
    """
    def __init__(self, session_manager=None, poll_interval_seconds: int = 60):
        self.poll_interval = poll_interval_seconds
        self._stop_event = threading.Event()
        self.registry = SymbolRegistry()
        self._thread = None
        self._zmq_thread = None
        self._heartbeat_thread = None
        
        # Raw Tick Buffers
        self._raw_buffers = {
            "options": [],
            "constituents": [],
            "underlying": [],
            "futures": []
        }
        
        # State Trackers (Memory)
        self.market_state = {
            "options": {},
            "constituents": {},
            "underlying": {},
            "futures": {}
        }
        
        self.last_minute_tracked = -1
        self.session_id = str(uuid.uuid4())
        
        self._buffer_lock = threading.Lock()
        self.sub = MessageBusSubscriber(FEED_PORT, topics=["TICK"])
        
        # Ensure directories exist
        for cat in self._raw_buffers.keys():
            (RAW_TICKS_DIR / cat).mkdir(parents=True, exist_ok=True)
            (CANONICAL_DIR / f"{cat}_state").mkdir(parents=True, exist_ok=True)
            
        (INSTITUTIONAL_MEMORY / "manifests").mkdir(parents=True, exist_ok=True)

    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("CanonicalCollector already running.")
            return
            
        self._stop_event.clear()
        
        self._zmq_thread = threading.Thread(target=self._listen_zmq, name="CanonicalZMQ", daemon=True)
        self._zmq_thread.start()
        
        self._thread = threading.Thread(target=self._run_loop, name="CanonicalFlusher", daemon=True)
        self._thread.start()
        
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="CanonicalHeartbeat", daemon=True)
        self._heartbeat_thread.start()
        
        logger.info(f"=== Canonical Observation Collector v3.1 Started ===")

    def stop(self):
        logger.info("CanonicalCollector stopping...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=30)
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=10)
        self.sub.close()
        logger.info("CanonicalCollector stopped.")

    def _get_category(self, token: str, symbol: str) -> str:
        symbol = str(symbol).upper()
        if symbol.endswith("CE") or symbol.endswith("PE"):
            return "options"
        elif symbol.endswith("FUT"):
            return "futures"
        elif symbol in ["NIFTY_50", "BANKNIFTY", "INDIA VIX", "SENSEX"] or token in ["26000", "26009", "99926017", "99919000"]:
            return "underlying"
        else:
            return "constituents"

    def _listen_zmq(self):
        def on_tick(topic, payload):
            if not self._stop_event.is_set():
                now = datetime.now()
                payload['local_observation_timestamp'] = now.isoformat() + "Z"
                
                token = str(payload.get('token', ''))
                raw_symbol = payload.get('symbol', '')
                
                # 1. Map to Universal Symbol
                symbol = self.registry.get_symbol(token, raw_symbol)
                
                if not symbol:
                    category = "options" if int(token) > 30000 else "constituents"
                    if token in ["26000", "99926017"]: category = "underlying"
                else:
                    category = self._get_category(token, symbol)
                
                # Replace broker token with universal symbol in payload for Parquet storage
                payload['symbol'] = symbol
                
                with self._buffer_lock:
                    # 1. Store Raw Tick
                    self._raw_buffers[category].append(payload)
                    
                    # 2. Update Live Canonical State (Indexed by SYMBOL, not token)
                    ltp = float(payload.get('last_traded_price', 0) / 100.0) if payload.get('last_traded_price') else 0.0
                    vol = payload.get('volume_trade_for_the_day', 0)
                    
                    if symbol not in self.market_state[category]:
                        self.market_state[category][symbol] = {
                            "token": token,
                            "open": ltp,
                            "high": ltp,
                            "low": ltp,
                            "close": ltp,
                            "volume_for_the_day": vol
                        }
                    else:
                        state = self.market_state[category][symbol]
                        state["close"] = ltp
                        state["volume_for_the_day"] = max(state["volume_for_the_day"], vol)
                        if ltp > state["high"]: state["high"] = ltp
                        if ltp > 0 and ltp < state["low"]: state["low"] = ltp
                        
                    # Option Specific Microstructure
                    if category == "options":
                        state = self.market_state[category][symbol]
                        if 'best_5_buy_data' in payload and payload['best_5_buy_data']:
                            state["best_bid_price"] = payload['best_5_buy_data'][0].get('price', 0) / 100.0
                            state["best_bid_qty"] = payload['best_5_buy_data'][0].get('quantity', 0)
                        if 'best_5_sell_data' in payload and payload['best_5_sell_data']:
                            state["best_ask_price"] = payload['best_5_sell_data'][0].get('price', 0) / 100.0
                            state["best_ask_qty"] = payload['best_5_sell_data'][0].get('quantity', 0)
                            
                        # Extract OI if available
                        if 'oi' in payload:
                            state["open_interest"] = payload['oi']

        logger.info("[CanonicalCollector] Listening to ZMQ FEED_PORT...")
        self.sub.listen(on_tick)

    def _run_loop(self):
        while not self._stop_event.is_set():
            now = datetime.now()
            
            # Flush exactly on minute rollover (e.g. 09:16:00, 09:17:00)
            if now.minute != self.last_minute_tracked:
                # Give a small 100ms grace period for late ticks belonging to previous minute
                time.sleep(0.1) 
                
                try:
                    if MarketCalendar.is_market_open(now) or MarketCalendar.is_preopen(now):
                        self._flush_canonical_snapshot(now)
                        self._flush_raw_ticks(now)
                    self.last_minute_tracked = now.minute
                except Exception as exc:
                    logger.error("CanonicalCollector flush error: %s", exc, exc_info=True)
                    
            time.sleep(0.5)
            
        # Final flush on shutdown
        now = datetime.now()
        self._flush_canonical_snapshot(now)
        self._flush_raw_ticks(now)

    def _heartbeat_loop(self):
        """Tier 1: Live Heartbeat Monitor"""
        while not self._stop_event.is_set():
            # Wait for 5 minutes
            for _ in range(60):
                if self._stop_event.is_set(): return
                time.sleep(5)
                
            now = datetime.now()
            # If the market is open (09:15 to 15:30) and we haven't tracked a minute recently
            if 9 <= now.hour <= 15:
                if now.hour == 9 and now.minute < 15: continue
                if now.hour == 15 and now.minute > 30: continue
                
                # Check if last_minute_tracked is within the last 5 minutes
                # This simple check warns if the ZMQ stream is dead
                diff = now.minute - self.last_minute_tracked
                if diff < 0: diff += 60
                
                if diff > 5:
                    logger.critical(f"HEALTH MONITOR [Tier 1]: NO DATA RECORDED for {diff} minutes! Is the ZMQ feed dead?")
                else:
                    logger.info("HEALTH MONITOR [Tier 1]: System is healthy. Data recording normally.")

    def _get_provenance_metadata(self):
        return {
            b"schema_version": b"v3.1",
            b"snapshot_version": b"v1.0",
            b"collector_version": b"v1.0",
            b"feed_version": b"AngelOne_SmartConnect_v3",
            b"exchange_name": b"NSE/NFO",
            b"timezone": b"Asia/Kolkata",
            b"observation_interval": b"60",
            b"market_session_id": self.session_id.encode('utf-8')
        }

    def _flush_canonical_snapshot(self, timestamp: datetime):
        with self._buffer_lock:
            # Deep copy the state to release lock quickly
            snapshot = {cat: dict(tokens) for cat, tokens in self.market_state.items()}
            
            # Reset OHLC for next minute, keep volume
            for cat in self.market_state:
                for sym in self.market_state[cat]:
                    last_close = self.market_state[cat][sym]["close"]
                    self.market_state[cat][sym]["open"] = last_close
                    self.market_state[cat][sym]["high"] = last_close
                    self.market_state[cat][sym]["low"] = last_close

        # Generate the exact same UUID5 as the BrainService does, based on pandas timestamp string
        ts_str = str(pd.Timestamp(timestamp.replace(second=0, microsecond=0)))
        obs_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, ts_str))
        date_str = timestamp.strftime("%Y/%m/%d")
        time_str = timestamp.strftime("%H:%M:00") # Lock to the minute boundary
        
        for category, tokens in snapshot.items():
            if not tokens: continue
            
            records = []
            for sym, data in tokens.items():
                record = data.copy()
                record["symbol"] = sym
                record["observation_uuid"] = obs_uuid
                record["local_observation_timestamp"] = time_str
                record["market_session_id"] = self.session_id
                records.append(record)
                
            df = pd.DataFrame(records)
            
            save_dir = CANONICAL_DIR / f"{category}_state" / date_str
            save_dir.mkdir(parents=True, exist_ok=True)
            
            # Save as minute chunks to avoid read-before-write latency
            file_name = f"state_{timestamp.strftime('%H%M')}.parquet"
            save_path = save_dir / file_name
            
            table = pa.Table.from_pandas(df)
            table = table.replace_schema_metadata(self._get_provenance_metadata())
            
            pq.write_table(table, save_path, compression="ZSTD")

    def _flush_raw_ticks(self, timestamp: datetime):
        with self._buffer_lock:
            records_to_flush = {cat: list(buf) for cat, buf in self._raw_buffers.items()}
            # Clear buffers
            for cat in self._raw_buffers:
                self._raw_buffers[cat].clear()
                
        date_str = timestamp.strftime("%Y/%m/%d")
        
        for category, records in records_to_flush.items():
            if not records: continue
            
            df = pd.DataFrame(records)
            
            save_dir = RAW_TICKS_DIR / category / date_str
            save_dir.mkdir(parents=True, exist_ok=True)
            
            file_name = f"ticks_{timestamp.strftime('%H%M')}.parquet"
            save_path = save_dir / file_name
            
            table = pa.Table.from_pandas(df)
            table = table.replace_schema_metadata(self._get_provenance_metadata())
            
            pq.write_table(table, save_path, compression="ZSTD")
            
        # Trigger manifest generation once a day or on stop, but here we can just update it
        # Manifests will be handled by a separate end-of-day script normally, but we can do it here for testing.
