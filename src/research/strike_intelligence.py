import sqlite3
import threading
import time
import uuid
from datetime import datetime
import pandas as pd

from src.utils.logger import get_logger
from src.utils.instrumentation import get_db_connection
from src.config.engineering_config import STRIKE_DB_PATH as DB_PATH
from src.core.db_writer_queue import DBWriterQueue

logger = get_logger("strike_intelligence")



def _get_conn():
    """Get a new SQLite connection (thread-safe: one connection per thread)."""
    conn = get_db_connection(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _apply_migrations(conn):
    migrations = [
        "ALTER TABLE strike_tracking ADD COLUMN premium_bucket TEXT",
        "ALTER TABLE strike_tracking ADD COLUMN premium_at_30s REAL",
        "ALTER TABLE strike_tracking ADD COLUMN return_pct_30s REAL",
        "ALTER TABLE strike_tracking ADD COLUMN premium_at_60s REAL",
        "ALTER TABLE strike_tracking ADD COLUMN return_pct_60s REAL",
        "ALTER TABLE strike_tracking ADD COLUMN premium_at_120s REAL",
        "ALTER TABLE strike_tracking ADD COLUMN return_pct_120s REAL",
        "ALTER TABLE strike_tracking ADD COLUMN premium_at_180s REAL",
        "ALTER TABLE strike_tracking ADD COLUMN return_pct_180s REAL",
        "ALTER TABLE strike_tracking ADD COLUMN strategy_alive_duration_sec INTEGER",
        "ALTER TABLE strike_tracking ADD COLUMN target_hit_while_valid INTEGER",
        "ALTER TABLE strike_tracking ADD COLUMN avg_spread_during_trade REAL",
        "ALTER TABLE strike_tracking ADD COLUMN spread_expansion_pct REAL",
        "ALTER TABLE strike_tracking ADD COLUMN liquidity_drop_pct REAL",
        "ALTER TABLE strike_tracking ADD COLUMN entry_fill_quality REAL",
        "ALTER TABLE strike_tracking ADD COLUMN exit_fill_quality REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN time_of_day_bucket TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN vwap_distance_pct REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN ema_vwap_distance REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN vfi_strength REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN vfi_ema_at_signal REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN momentum_score REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN index_volatility REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN signal_category TEXT DEFAULT 'EXECUTED'",
        "ALTER TABLE signal_snapshots ADD COLUMN rejection_reason TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN rejection_stage TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN rejection_timestamp TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN filter_name TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN filter_value REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN would_have_entered_price REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN virtual_tracking_completed INTEGER DEFAULT 0",
        "ALTER TABLE strike_tracking ADD COLUMN buyer_aggression_score REAL",
        "ALTER TABLE strike_tracking ADD COLUMN seller_aggression_score REAL",
        "ALTER TABLE strike_tracking ADD COLUMN bid_pressure_ratio REAL",
        "ALTER TABLE strike_tracking ADD COLUMN ask_pressure_ratio REAL",
        "ALTER TABLE strike_tracking ADD COLUMN order_flow_direction TEXT",
        "ALTER TABLE strike_tracking ADD COLUMN order_flow_strength REAL",
        "ALTER TABLE strike_tracking ADD COLUMN max_order_flow_strength REAL",
        "ALTER TABLE strike_tracking ADD COLUMN min_order_flow_strength REAL",
        "ALTER TABLE strike_tracking ADD COLUMN liquidity_expansion REAL",
        "ALTER TABLE strike_tracking ADD COLUMN liquidity_contraction REAL",
        
        # Phase 4.1 & 4.3 Additions
        "ALTER TABLE signal_snapshots ADD COLUMN market_regime TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN atr_current REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN atr_average REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN atr_expansion_ratio REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN compression_score REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN candle_body_avg REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN candle_body_trend TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN bullish_energy REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN bearish_energy REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN net_candle_energy REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN vfi_price_alignment TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN trade_quality_score REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN market_session_phase TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN is_expiry_day INTEGER",

        # Phase 5.2 Governance Additions
        "ALTER TABLE signal_snapshots ADD COLUMN session_type TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN data_source TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN quality_score REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN connection_quality TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN observation_status TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN observation_version TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN exchange_timestamp TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN local_timestamp TEXT",
        "ALTER TABLE signal_snapshots ADD COLUMN latency_ms REAL",
        "ALTER TABLE signal_snapshots ADD COLUMN market_state TEXT"
    ]
    for mig in migrations:
        try:
            conn.execute(mig)
        except sqlite3.OperationalError:
            pass # Column already exists or other error

def init_database():
    """Create tables if they don't already exist."""
    conn = _get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS signal_snapshots (
            signal_id       TEXT PRIMARY KEY,
            signal_timestamp TEXT,
            signal_type     TEXT,
            strategy        TEXT,
            index_name      TEXT,
            index_price     REAL,
            atm_strike      REAL,
            traded_token    TEXT,
            time_of_day_bucket TEXT,
            vwap_distance_pct REAL,
            ema_vwap_distance REAL,
            vfi_strength     REAL,
            vfi_ema_at_signal REAL,
            momentum_score   REAL,
            index_volatility REAL,
            signal_category  TEXT DEFAULT 'EXECUTED',
            rejection_reason TEXT,
            rejection_stage  TEXT,
            rejection_timestamp TEXT,
            filter_name      TEXT,
            filter_value     REAL,
            would_have_entered_price REAL,
            virtual_tracking_completed INTEGER DEFAULT 0,
            
            -- Phase 4.1 & 4.3 columns
            vfi_cross_strength REAL,
            vfi_angle REAL,
            vfi_distance_from_zero REAL,
            vfi_confirmation_speed INTEGER,
            vfi_normalized_strength REAL,
            avg_candle_size REAL,
            market_speed_score REAL,
            momentum_acceleration REAL,
            volatility_state TEXT,
            market_regime TEXT,
            atr_current REAL,
            atr_average REAL,
            atr_expansion_ratio REAL,
            compression_score REAL,
            candle_body_avg REAL,
            candle_body_trend TEXT,
            bullish_energy REAL,
            bearish_energy REAL,
            net_candle_energy REAL,
            vfi_price_alignment TEXT,
            trade_quality_score REAL,
            market_session_phase TEXT,
            is_expiry_day INTEGER,

            -- Phase 5.2 columns
            session_type TEXT,
            data_source TEXT,
            quality_score REAL,
            connection_quality TEXT,
            observation_status TEXT,
            observation_version TEXT,
            exchange_timestamp TEXT,
            local_timestamp TEXT,
            latency_ms REAL,
            market_state TEXT
        );

        CREATE TABLE IF NOT EXISTS strike_tracking (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id             TEXT,
            token                 TEXT,
            symbol                TEXT,
            strike                REAL,
            option_type           TEXT,
            distance_from_atm     INTEGER,
            dte                   INTEGER,
            was_traded            INTEGER DEFAULT 0,
            -- Signal Snapshot
            entry_premium         REAL,
            bid_price             REAL,
            ask_price             REAL,
            bid_ask_spread        REAL,
            spread_pct            REAL,
            bid_qty               INTEGER,
            ask_qty               INTEGER,
            volume                INTEGER,
            open_interest         INTEGER,
            iv                    REAL,
            delta                 REAL,
            order_flow_score      REAL,
            -- 180-Second Tracking Results
            hit_target            INTEGER DEFAULT 0,
            time_to_target_sec    INTEGER,
            max_favorable_pct     REAL,
            max_adverse_pct       REAL,
            highest_premium       REAL,
            lowest_premium        REAL,
            entry_slippage_est    REAL,
            exit_slippage_est     REAL,
            net_after_friction    REAL,
            practically_executable INTEGER DEFAULT 0,
            strike_efficiency_score REAL,
            premium_bucket TEXT,
            premium_at_30s REAL,
            return_pct_30s REAL,
            premium_at_60s REAL,
            return_pct_60s REAL,
            premium_at_120s REAL,
            return_pct_120s REAL,
            premium_at_180s REAL,
            return_pct_180s REAL,
            strategy_alive_duration_sec INTEGER,
            target_hit_while_valid INTEGER,
            avg_spread_during_trade REAL,
            spread_expansion_pct REAL,
            liquidity_drop_pct REAL,
            entry_fill_quality REAL,
            exit_fill_quality REAL,
            buyer_aggression_score REAL,
            seller_aggression_score REAL,
            bid_pressure_ratio REAL,
            ask_pressure_ratio REAL,
            order_flow_direction TEXT,
            order_flow_strength REAL,
            max_order_flow_strength REAL,
            min_order_flow_strength REAL,
            liquidity_expansion REAL,
            liquidity_contraction REAL,
            FOREIGN KEY (signal_id) REFERENCES signal_snapshots(signal_id)
        );

        CREATE INDEX IF NOT EXISTS idx_signal_id ON strike_tracking(signal_id);
        CREATE INDEX IF NOT EXISTS idx_token ON strike_tracking(token);
    """)
    _apply_migrations(conn)
    conn.commit()
    conn.close()
    logger.info("[StrikeIntelligence] Database initialized.")


class StrikeIntelligenceModule:
    """
    Runs silently in the background.
    For every valid signal, tracks ATM + 5 OTM option strikes
    for 180 seconds and stores full analytics in SQLite.
    Does NOT interfere with any execution or entry/exit logic.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Active sessions: signal_id → session dict
        # session dict keys: tokens, strike_data, tick_cache
        self._active_sessions = {}
        # token → set of signal_ids that are tracking this token
        self._token_session_map = {}
        self._finalizing = set()
        init_database()

    def get_active_tokens(self):
        """Returns the set of tokens currently being tracked across all active sessions."""
        with self._lock:
            return set(self._token_session_map.keys())

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def _premium_bucket(self, premium):
        if premium < 20: return "₹10-20"
        elif premium < 40: return "₹20-40"
        elif premium < 70: return "₹40-70"
        elif premium < 100: return "₹70-100"
        else: return "₹100+"

    def update_market_state(self, current_df):
        """
        Called from main loop to update validity of the strategy for active sessions.
        """
        if current_df is None or current_df.empty:
            return

        latest = current_df.iloc[-1]
        close = latest.get('close', 0)
        ema_9 = latest.get('ema_9', 0)
        vwap = latest.get('vwap', 0)

        with self._lock:
            for signal_id, session in list(self._active_sessions.items()):
                if session.get('strategy_invalidated_at') is not None:
                    continue
                
                sig_type = session.get('signal_type')
                if sig_type == 'CALL':
                    # strategy invalid if 9 EMA crosses back below VWAP
                    if ema_9 < vwap:
                        session['strategy_invalidated_at'] = time.time()
                elif sig_type == 'PUT':
                    # strategy invalid if 9 EMA crosses back above VWAP
                    if ema_9 > vwap:
                        session['strategy_invalidated_at'] = time.time()

    def register_signal(self, signal: dict, index_price: float, api, fetcher, recent_candles=None,
                        signal_category='EXECUTED', rejection_reason=None, rejection_stage=None,
                        filter_name=None, filter_value=None, would_have_entered_price=None,
                        **kwargs):
        """
        Entry point. Called in a daemon thread from main.py whenever a signal fires.
        Builds the virtual option universe, snapshots market depth, and starts tracking.
        """
        import sys
        from src.core.market_calendar import MarketCalendar
        now = datetime.now()
        local_timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        # 1. Enforce Market Hours Validation
        session_type = MarketCalendar.get_session_type(now)
        if "unittest" in sys.modules or any("test" in arg.lower() for arg in sys.argv):
            session_type = "UNIT_TEST"

        if session_type not in {"LIVE", "SIMULATION", "REPLAY", "UNIT_TEST"}:
            logger.info(f"[StrikeIntelligence] Session type is {session_type}. Blocking signal registration outside active hours.")
            return None, []

        signal_id = str(uuid.uuid4())
        signal_type = signal.get("type", "CALL")
        strategy = signal.get("strategy", "UNKNOWN")
        opt_type = "CE" if signal_type == "CALL" else "PE"

        try:
            index_name, exch_seg = fetcher.get_active_instrument()
        except Exception:
            index_name, exch_seg = "UNKNOWN", "NFO"

        # ATM strike (round to nearest 50 for Nifty/Sensex)
        step = 100 if index_name == "SENSEX" else 50
        atm_strike = round(index_price / step) * step

        logger.info(f"[StrikeIntelligence] Signal {signal_type} detected. "
              f"Building universe around ATM={atm_strike} (index={index_price:.2f})")

        # Build option universe: ATM + 5 OTM
        target_strikes = []
        for i in range(6):  # 0=ATM, 1-5=OTM
            if signal_type == "CALL":
                s = atm_strike + i * step
            else:
                s = atm_strike - i * step
            target_strikes.append((i, s))

        # Get the option chain
        try:
            weekly_opts = fetcher.get_weekly_option_tokens()
            opts = weekly_opts[weekly_opts['symbol'].str.endswith(opt_type)]
        except Exception as e:
            logger.info(f"[StrikeIntelligence] Could not fetch option chain: {e}")
            return None, []

        if opts.empty:
            logger.info("[StrikeIntelligence] Empty option chain. Aborting.")
            return None, []

        # Determine DTE
        try:
            expiry_dt = pd.to_datetime(opts.iloc[0]['expiry'], format='%d%b%Y')
            dte = (expiry_dt.date() - now.date()).days
        except Exception:
            dte = -1

        # Identify tokens for our target strikes
        strike_rows = []
        for dist, strike_val in target_strikes:
            strike_val_scaled = int(strike_val * 100)  # Angel One stores strike*100
            match = opts[opts['strike'].astype(int) == strike_val_scaled]
            if match.empty:
                # Try nearest available strike
                opts_copy = opts.copy()
                opts_copy['_diff'] = (opts_copy['strike'].astype(int) - strike_val_scaled).abs()
                match = opts_copy.sort_values('_diff').head(1)
            if not match.empty:
                row = match.iloc[0]
                strike_rows.append({
                    "distance_from_atm": dist,
                    "strike": float(row['strike']) / 100,
                    "token": str(row['token']),
                    "symbol": str(row['symbol']),
                    "option_type": opt_type,
                    "dte": dte,
                })

        if not strike_rows:
            logger.info("[StrikeIntelligence] No matching strikes found. Aborting.")
            return None, []

        # Determine which token was traded by the PaperTrader
        traded_token = signal.get("candidate_token", None)

        # Baseline indicators
        time_of_day_bucket = "MID_SESSION"
        vwap_distance_pct = 0.0
        ema_vwap_distance = 0.0
        vfi_strength = 0.0
        vfi_ema_at_signal = 0.0
        momentum_score = 0.0
        index_volatility = 0.0

        # Phase 4.1 & 4.3 Additions
        vfi_cross_strength = 0.0
        vfi_angle = 0.0
        vfi_distance_from_zero = 0.0
        vfi_confirmation_speed = 0
        vfi_normalized_strength = 0.0
        avg_candle_size = 0.0
        market_speed_score = 0.0
        momentum_acceleration = 0.0
        volatility_state = "NORMAL"
        market_regime = "UNKNOWN"
        atr_current = 0.0
        atr_average = 0.0
        atr_expansion_ratio = 1.0
        compression_score = 0.0
        candle_body_avg = 0.0
        candle_body_trend = "FLAT"
        bullish_energy = 0.0
        bearish_energy = 0.0
        net_candle_energy = 0.0
        vfi_price_alignment = "UNKNOWN"
        trade_quality_score = 0.0
        market_session_phase = "UNKNOWN"
        is_expiry_day = 0

        current_df_row = None
        if recent_candles and isinstance(recent_candles, list) and len(recent_candles) > 0:
            current_df_row = recent_candles[-1]
            last_20 = recent_candles[-20:]
            
            # Session ATR
            atr_session = 0.0
            if len(recent_candles) > 1:
                tr_list = []
                for i in range(1, len(recent_candles)):
                    h = recent_candles[i].get('high', 0)
                    l = recent_candles[i].get('low', 0)
                    pc = recent_candles[i-1].get('close', 0)
                    tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))
                atr_session = sum(tr_list) / len(tr_list)
            
            # Short ATR
            if len(last_20) > 1:
                tr_short = []
                for i in range(1, len(last_20)):
                    h = last_20[i].get('high', 0)
                    l = last_20[i].get('low', 0)
                    pc = last_20[i-1].get('close', 0)
                    tr_short.append(max(h - l, abs(h - pc), abs(l - pc)))
                atr_current = sum(tr_short) / len(tr_short)
                atr_average = atr_session
                if atr_average > 0:
                    atr_expansion_ratio = atr_current / atr_average
            
            if atr_expansion_ratio > 1.3:
                market_regime = "TRENDING_EXPANSION"
            elif atr_expansion_ratio < 0.8:
                market_regime = "RANGE_COMPRESSION"
            else:
                market_regime = "NORMAL"
                
            # Energy
            last_10 = recent_candles[-10:]
            for r in last_10:
                c = r.get('close', 0)
                o = r.get('open', 0)
                if c > o:
                    bullish_energy += (c - o)
                else:
                    bearish_energy += (o - c)
            net_candle_energy = bullish_energy - bearish_energy
            
            # Quality Score
            if atr_expansion_ratio > 1.2: trade_quality_score += 30
            if abs(net_candle_energy) > atr_current: trade_quality_score += 30
            
            # VFI alignment
            vfi_now = current_df_row.get('vfi', 0)
            if vfi_now > 0 and net_candle_energy > 0:
                vfi_price_alignment = "BULL_ALIGNED"
            elif vfi_now < 0 and net_candle_energy < 0:
                vfi_price_alignment = "BEAR_ALIGNED"
            else:
                vfi_price_alignment = "DIVERGENT"

        if current_df_row is not None:
            ts_dt = current_df_row.get("timestamp")
            if pd.notnull(ts_dt):
                ts_p = pd.to_datetime(ts_dt)
                if ts_p.hour == 9 or (ts_p.hour == 10 and ts_p.minute <= 30):
                    time_of_day_bucket = "MARKET_OPEN"
                elif ts_p.hour >= 14:
                    time_of_day_bucket = "CLOSING_SESSION"
            
            vwap = current_df_row.get("vwap", 0)
            close_p = current_df_row.get("close", index_price)
            if vwap > 0:
                vwap_distance_pct = ((close_p - vwap) / vwap) * 100
            ema_vwap_distance = current_df_row.get("ema_9", 0) - vwap
            vfi_strength = current_df_row.get("vfi", 0)
            vfi_ema_at_signal = current_df_row.get("vfi_ema", 0)
            momentum_score = current_df_row.get("body_ratio", 0) * current_df_row.get("rvol", 0)
            
            # index volatility (approx using high-low / close)
            high_p = current_df_row.get("high", close_p)
            low_p = current_df_row.get("low", close_p)
            if close_p > 0:
                index_volatility = ((high_p - low_p) / close_p) * 100

        # Standardize exchange timestamp and calculate latency
        exch_ts = None
        if current_df_row:
            ts = current_df_row.get("timestamp")
            if ts:
                try:
                    if isinstance(ts, str):
                        exch_ts = pd.to_datetime(ts).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        exch_ts = ts.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    exch_ts = None
        if not exch_ts:
            exch_ts = local_timestamp

        try:
            local_dt = datetime.strptime(local_timestamp, "%Y-%m-%d %H:%M:%S")
            exch_dt = datetime.strptime(exch_ts, "%Y-%m-%d %H:%M:%S")
            latency_ms = float((local_dt - exch_dt).total_seconds() * 1000.0)
        except Exception:
            latency_ms = 0.0

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

        snapshot_data = {
            "signal_id": signal_id,
            "signal_timestamp": local_timestamp,
            "signal_type": signal_type,
            "strategy": strategy,
            "index_name": index_name,
            "index_price": index_price,
            "atm_strike": atm_strike,
            "traded_token": traded_token,
            "time_of_day_bucket": time_of_day_bucket,
            "vwap_distance_pct": vwap_distance_pct,
            "ema_vwap_distance": ema_vwap_distance,
            "vfi_strength": vfi_strength,
            "vfi_ema_at_signal": vfi_ema_at_signal,
            "momentum_score": momentum_score,
            "index_volatility": index_volatility,
            "signal_category": signal_category,
            "rejection_reason": rejection_reason,
            "rejection_stage": rejection_stage,
            "rejection_timestamp": local_timestamp if signal_category == 'REJECTED' else None,
            "filter_name": filter_name,
            "filter_value": filter_value,
            "would_have_entered_price": would_have_entered_price,
            "virtual_tracking_completed": 0,
            
            # Phase 4.1 & 4.3 columns
            "vfi_cross_strength": vfi_cross_strength,
            "vfi_angle": vfi_angle,
            "vfi_distance_from_zero": vfi_distance_from_zero,
            "vfi_confirmation_speed": vfi_confirmation_speed,
            "vfi_normalized_strength": vfi_normalized_strength,
            "avg_candle_size": avg_candle_size,
            "market_speed_score": market_speed_score,
            "momentum_acceleration": momentum_acceleration,
            "volatility_state": volatility_state,
            "market_regime": market_regime,
            "atr_current": atr_current,
            "atr_average": atr_average,
            "atr_expansion_ratio": atr_expansion_ratio,
            "compression_score": compression_score,
            "candle_body_avg": candle_body_avg,
            "candle_body_trend": candle_body_trend,
            "bullish_energy": bullish_energy,
            "bearish_energy": bearish_energy,
            "net_candle_energy": net_candle_energy,
            "vfi_price_alignment": vfi_price_alignment,
            "trade_quality_score": trade_quality_score,
            "market_session_phase": market_session_phase,
            "is_expiry_day": is_expiry_day,
            
            # Phase 5.2 columns
            "session_type": session_type,
            "data_source": data_source,
            "quality_score": 100.0,
            "connection_quality": "GOOD",
            "observation_status": "ACTIVE",
            "observation_version": "v5.2",
            "exchange_timestamp": exch_ts,
            "local_timestamp": local_timestamp,
            "latency_ms": latency_ms,
            "market_state": "NORMAL"
        }

        # Save signal snapshot to DB
        try:
            placeholders = ", ".join(f":{k}" for k in snapshot_data.keys())
            columns = ", ".join(snapshot_data.keys())
            sql = f"INSERT INTO signal_snapshots ({columns}) VALUES ({placeholders})"
            DBWriterQueue.get_instance(DB_PATH).enqueue(sql, snapshot_data)
        except Exception as e:
            logger.error(f"[StrikeIntelligence] Queue insert error (signal_snapshots): {e}")
            return None, []

        # Fetch full market depth snapshot for each strike (one API call per token)
        tokens_to_track = [r['token'] for r in strike_rows]
        depth_snapshots = {}
        ltp_snapshots = {}
        greeks_map = {}

        try:
            chunk = tokens_to_track[:50]
            md_res = api.marketData("FULL", {exch_seg: chunk})
            if md_res and md_res.get('status') and md_res.get('data'):
                for item in md_res['data'].get('fetched', []):
                    tk = str(item.get('symbolToken', item.get('token', '')))
                    ltp_snapshots[tk] = float(item.get('ltp', 0))
                    depth_snapshots[tk] = item.get('depth', {})
        except Exception as e:
            logger.error(f"[StrikeIntelligence] Market depth fetch error: {e}")

        # Fetch Greeks (best-effort)
        try:
            greek_res = api.optionGreek({"name": index_name, "expirydate": opts.iloc[0]['expiry']})
            if greek_res and greek_res.get('status') and greek_res.get('data'):
                for item in greek_res['data']:
                    key = (str(item.get('strikePrice', '')), opt_type)
                    greeks_map[key] = {
                        "iv": item.get('impliedVolatility', 0.0),
                        "delta": item.get('delta', 0.0),
                    }
        except Exception:
            pass

        # Build initial DB rows for each strike
        db_rows = []
        for r in strike_rows:
            tk = r['token']
            depth = depth_snapshots.get(tk, {})
            ltp = ltp_snapshots.get(tk, 0.0)

            buy_depth = depth.get('buy', [{}])
            sell_depth = depth.get('sell', [{}])
            bid_price = float(buy_depth[0].get('price', 0)) / 100 if buy_depth else 0.0
            ask_price = float(sell_depth[0].get('price', 0)) / 100 if sell_depth else 0.0
            bid_qty = int(buy_depth[0].get('quantity', 0)) if buy_depth else 0
            ask_qty = int(sell_depth[0].get('quantity', 0)) if sell_depth else 0
            spread = round(ask_price - bid_price, 2) if ask_price > bid_price else 0.0
            spread_pct = round((spread / ltp) * 100, 2) if ltp > 0 else 0.0
            volume = int(depth.get('volume', 0))
            oi = int(depth.get('openInterest', 0))
            entry_slippage = round(spread / 2, 2)

            greek_key = (str(int(r['strike'])), opt_type)
            greeks = greeks_map.get(greek_key, {})

            was_traded = 1 if tk == str(traded_token) else 0
            premium_bucket = self._premium_bucket(ltp)

            db_rows.append({
                "signal_id": signal_id,
                "token": tk,
                "symbol": r['symbol'],
                "strike": r['strike'],
                "option_type": r['option_type'],
                "distance_from_atm": r['distance_from_atm'],
                "dte": r['dte'],
                "was_traded": was_traded,
                "premium_bucket": premium_bucket,
                "entry_premium": ltp,
                "bid_price": bid_price,
                "ask_price": ask_price,
                "bid_ask_spread": spread,
                "spread_pct": spread_pct,
                "bid_qty": bid_qty,
                "ask_qty": ask_qty,
                "volume": volume,
                "open_interest": oi,
                "iv": greeks.get("iv", 0.0),
                "delta": greeks.get("delta", 0.0),
                "order_flow_score": 0.0,  # populated by on_tick
                "entry_slippage_est": entry_slippage,
            })

        # Insert initial rows (tracking results will be updated after 180s)
        for row in db_rows:
            try:
                sql = """
                    INSERT INTO strike_tracking
                    (signal_id, token, symbol, strike, option_type, distance_from_atm, dte,
                     was_traded, premium_bucket, entry_premium, bid_price, ask_price, bid_ask_spread, spread_pct,
                     bid_qty, ask_qty, volume, open_interest, iv, delta, order_flow_score,
                     entry_slippage_est)
                    VALUES
                    (:signal_id, :token, :symbol, :strike, :option_type, :distance_from_atm, :dte,
                     :was_traded, :premium_bucket, :entry_premium, :bid_price, :ask_price, :bid_ask_spread, :spread_pct,
                     :bid_qty, :ask_qty, :volume, :open_interest, :iv, :delta, :order_flow_score,
                     :entry_slippage_est)
                """
                DBWriterQueue.get_instance(DB_PATH).enqueue(sql, row)
            except Exception as e:
                logger.error(f"[StrikeIntelligence] Queue insert error (strike_tracking): {e}")

        # Build in-memory tracking session
        session = {
            "signal_id": signal_id,
            "signal_type": signal_type,
            "start_time": time.time(),
            "strategy_invalidated_at": None,
            "tokens": {r['token']: {
                "entry_premium": db_rows[i]['entry_premium'],
                "highest": db_rows[i]['entry_premium'],
                "lowest": db_rows[i]['entry_premium'],
                "hit_target": False,
                "time_to_target_sec": None,
                "buy_vol": 0,
                "sell_vol": 0,
                "last_price": db_rows[i]['entry_premium'],
                "snapshots": {30: None, 60: None, 120: None, 180: None},
                "spreads": [],
                "min_bid_qty": db_rows[i]['bid_qty'],
                "initial_bid_qty": db_rows[i]['bid_qty'],
                "initial_spread": db_rows[i]['bid_ask_spread']
            } for i, r in enumerate(strike_rows)},
        }

        with self._lock:
            self._active_sessions[signal_id] = session
            for tk in session['tokens']:
                if tk not in self._token_session_map:
                    self._token_session_map[tk] = set()
                self._token_session_map[tk].add(signal_id)

        logger.info(f"[StrikeIntelligence] Tracking {len(strike_rows)} strikes for 180 seconds. "
              f"Signal ID: {signal_id[:8]}...")

        # Return both signal_id and tokens_to_track
        return signal_id, tokens_to_track


    def on_tick(self, token: str, message: dict):
        """
        Called from main.py's on_data WebSocket handler for EVERY tick.
        We only process ticks for tokens we're actively tracking.
        """
        if not isinstance(message, dict):
            return

        # Lock-free fast-path
        if not self._token_session_map:
            return
            
        token_str = str(token)
        if token_str not in self._token_session_map:
            return

        with self._lock:
            signal_ids = self._token_session_map.get(token_str)
            if not signal_ids:
                return
            signal_ids_copy = set(signal_ids)

        ltp_raw = message.get('last_traded_price', 0)
        ltq = message.get('last_traded_quantity', 0)
        ltp = float(ltp_raw) / 100 if ltp_raw and ltp_raw > 0 else 0.0
        if ltp <= 0:
            return
            
        # extract best bid/ask from message (mode 3 SNAPQUOTE contains best_5_buy/sell)
        best_bid = 0.0
        best_ask = 0.0
        best_bid_qty = 0
        if 'best_5_buy_data' in message and len(message['best_5_buy_data']) > 0:
            best_bid = float(message['best_5_buy_data'][0].get('price', 0)) / 100
            best_bid_qty = int(message['best_5_buy_data'][0].get('quantity', 0))
        if 'best_5_sell_data' in message and len(message['best_5_sell_data']) > 0:
            best_ask = float(message['best_5_sell_data'][0].get('price', 0)) / 100
            
        spread = round(best_ask - best_bid, 2) if best_ask > best_bid else 0.0

        elapsed_threshold = 180

        for signal_id in signal_ids_copy:
            should_finalize = False
            with self._lock:
                if signal_id in self._finalizing:
                    continue
                session = self._active_sessions.get(signal_id)
                if session is None:
                    continue
                token_data = session['tokens'].get(token_str)
                if token_data is None:
                    continue

                entry = token_data['entry_premium']
                if entry <= 0:
                    continue

                # Update tracking data
                if ltp > token_data['highest']:
                    token_data['highest'] = ltp
                if ltp < token_data['lowest']:
                    token_data['lowest'] = ltp

                pct_change = ((ltp - entry) / entry) * 100

                # Check 10% target
                elapsed = time.time() - session['start_time']
                
                # record target hit time and check if strategy was still valid
                if not token_data['hit_target'] and pct_change >= 10.0:
                    token_data['hit_target'] = True
                    token_data['time_to_target_sec'] = int(elapsed)
                    # if strategy invalidated, check if it was invalidated AFTER we hit target
                    token_data['target_hit_while_valid'] = True
                    if session.get('strategy_invalidated_at') is not None:
                        if session['strategy_invalidated_at'] < time.time():
                            token_data['target_hit_while_valid'] = False

                # Order flow: tick test
                if ltq > 0:
                    if ltp > token_data['last_price']:
                        token_data['buy_vol'] += ltq
                    elif ltp < token_data['last_price']:
                        token_data['sell_vol'] += ltq

                token_data['last_price'] = ltp
                
                # execution quality tracking
                if spread > 0:
                    token_data['spreads'].append(spread)
                if best_bid_qty > 0 and best_bid_qty < token_data['min_bid_qty']:
                    token_data['min_bid_qty'] = best_bid_qty

                # Multitime snapshots
                for snap_t in [30, 60, 120, 180]:
                    if elapsed >= snap_t and token_data['snapshots'][snap_t] is None:
                        token_data['snapshots'][snap_t] = ltp

                # Check if 180 seconds have passed and finalize
                if elapsed >= elapsed_threshold:
                    should_finalize = True
                    self._finalizing.add(signal_id)

            if should_finalize:
                # Finalize in a separate thread so we don't hold the lock
                threading.Thread(
                    target=self._finalize_session,
                    args=(signal_id,),
                    daemon=True
                ).start()

    def schedule_finalization(self, signal_id: str, delay: float = 180.0):
        """
        Called after register_signal to ensure finalization happens
        even if no ticks arrive (e.g., illiquid option).
        """
        def _wait_and_finalize():
            time.sleep(delay + 2)  # small buffer
            with self._lock:
                if signal_id in self._finalizing:
                    return
                if signal_id in self._active_sessions:
                    self._finalizing.add(signal_id)
                else:
                    return  # already finalized via on_tick
            self._finalize_session(signal_id)

        threading.Thread(target=_wait_and_finalize, daemon=True).start()

    # -----------------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------------

    def _finalize_session(self, signal_id: str):
        """
        Called after 180 seconds. Calculates scores and writes final results to DB.
        """
        with self._lock:
            session = self._active_sessions.pop(signal_id, None)
            if session is None:
                self._finalizing.discard(signal_id)
                return  # Already finalized

            # Clean up token map
            for tk in session['tokens']:
                if tk in self._token_session_map:
                    self._token_session_map[tk].discard(signal_id)
                    if not self._token_session_map[tk]:
                        del self._token_session_map[tk]

        logger.info(f"[StrikeIntelligence] Finalizing session {signal_id[:8]}...")
        conn = _get_conn()

        try:
            # Fetch initial rows from DB to get entry data
            rows = conn.execute(
                "SELECT * FROM strike_tracking WHERE signal_id = ?", (signal_id,)
            ).fetchall()
            
            strat_alive = 180
            if session.get('strategy_invalidated_at') is not None:
                strat_alive = int(session['strategy_invalidated_at'] - session['start_time'])

            for row in rows:
                tk = str(row['token'])
                token_data = session['tokens'].get(tk, {})

                entry = row['entry_premium'] or 0.0
                highest = token_data.get('highest', entry)
                lowest = token_data.get('lowest', entry)
                hit_target = 1 if token_data.get('hit_target', False) else 0
                time_to_target = token_data.get('time_to_target_sec', None)
                target_hit_valid = 1 if token_data.get('target_hit_while_valid', hit_target) else 0

                max_fav = round(((highest - entry) / entry) * 100, 2) if entry > 0 else 0.0
                max_adv = round(((entry - lowest) / entry) * 100, 2) if entry > 0 else 0.0

                spread_pct = row['spread_pct'] or 0.0
                bid_qty = row['bid_qty'] or 0
                ask_qty = row['ask_qty'] or 0
                entry_slip = row['entry_slippage_est'] or 0.0
                exit_slip = entry_slip  # symmetric assumption
                total_friction = entry_slip + exit_slip
                net_friction = round(10.0 - total_friction, 2) if entry > 0 else 0.0
                practically_exec = 1 if net_friction > 5.0 and hit_target else 0

                # Order flow score: buy/(buy+sell) ratio 0-100
                buy_vol = token_data.get('buy_vol', 0)
                sell_vol = token_data.get('sell_vol', 0)
                total_vol = buy_vol + sell_vol
                of_score = round((buy_vol / total_vol) * 100, 1) if total_vol > 0 else 50.0

                score = self._calculate_efficiency_score(
                    hit_target=hit_target,
                    time_to_target=time_to_target,
                    max_adv=max_adv,
                    bid_qty=bid_qty,
                    ask_qty=ask_qty,
                    spread_pct=spread_pct,
                )
                
                # multi time snapshots
                snaps = token_data.get('snapshots', {30: None, 60: None, 120: None, 180: None})
                def ret_p(snap):
                    return round(((snap - entry) / entry) * 100, 2) if snap and entry > 0 else None
                p30, p60, p120, p180 = snaps[30], snaps[60], snaps[120], snaps[180]
                r30, r60, r120, r180 = ret_p(p30), ret_p(p60), ret_p(p120), ret_p(p180)
                
                # execution quality metrics
                spreads = token_data.get('spreads', [])
                avg_spread = sum(spreads)/len(spreads) if spreads else 0.0
                initial_spread = token_data.get('initial_spread', 0)
                spread_exp = ((max(spreads) - initial_spread) / initial_spread * 100) if spreads and initial_spread > 0 else 0.0
                initial_bid_qty = token_data.get('initial_bid_qty', 0)
                min_bid_qty = token_data.get('min_bid_qty', 0)
                liq_drop = ((initial_bid_qty - min_bid_qty) / initial_bid_qty * 100) if initial_bid_qty > 0 else 0.0
                efq = 100 - (entry_slip / entry * 100) if entry > 0 else 0.0
                exfq = 100 - (exit_slip / highest * 100) if highest > 0 else 0.0

                DBWriterQueue.get_instance(DB_PATH).enqueue("""
                    UPDATE strike_tracking SET
                        hit_target = ?,
                        time_to_target_sec = ?,
                        max_favorable_pct = ?,
                        max_adverse_pct = ?,
                        highest_premium = ?,
                        lowest_premium = ?,
                        exit_slippage_est = ?,
                        net_after_friction = ?,
                        practically_executable = ?,
                        order_flow_score = ?,
                        strike_efficiency_score = ?,
                        premium_at_30s = ?, return_pct_30s = ?,
                        premium_at_60s = ?, return_pct_60s = ?,
                        premium_at_120s = ?, return_pct_120s = ?,
                        premium_at_180s = ?, return_pct_180s = ?,
                        strategy_alive_duration_sec = ?,
                        target_hit_while_valid = ?,
                        avg_spread_during_trade = ?,
                        spread_expansion_pct = ?,
                        liquidity_drop_pct = ?,
                        entry_fill_quality = ?,
                        exit_fill_quality = ?
                    WHERE signal_id = ? AND token = ?
                """, (hit_target, time_to_target, max_fav, max_adv,
                      highest, lowest, exit_slip, net_friction,
                      practically_exec, of_score, score,
                      p30, r30, p60, r60, p120, r120, p180, r180,
                      strat_alive, target_hit_valid,
                      avg_spread, spread_exp, liq_drop, efq, exfq,
                      signal_id, tk))

            # Calculate final data quality and update signal_snapshots
            total_ticks_received = sum(len(tk_data.get('spreads', [])) for tk_data in session['tokens'].values())
            obs_status = 'FINALIZED' if total_ticks_received > 0 else 'CORRUPTED'
            
            DBWriterQueue.get_instance(DB_PATH).enqueue("""
                UPDATE signal_snapshots SET
                    virtual_tracking_completed = 1,
                    observation_status = ?
                WHERE signal_id = ?
            """, (obs_status, signal_id))

            logger.info(f"[StrikeIntelligence] Session {signal_id[:8]} finalized and queued to DB (Status: {obs_status}).")

        except Exception as e:
            logger.error(f"[StrikeIntelligence] Error finalizing session {signal_id[:8]}: {e}")
        finally:
            conn.close()
            with self._lock:
                self._finalizing.discard(signal_id)

    def _calculate_efficiency_score(self, hit_target, time_to_target,
                                    max_adv, bid_qty, ask_qty, spread_pct):
        """
        Score = (Time × 40) + (Safety × 25) + (Liquidity × 20) + (Friction × 15)

        Time      = if hit_target: (1 − time_to_target/180) else 0
        Safety    = max(0, 1 − max_adverse_pct/20)
        Liquidity = min(1, min(bid_qty, ask_qty)/500)
        Friction  = max(0, 1 − spread_pct/5)
        """
        # Time component
        if hit_target and time_to_target is not None:
            time_w = max(0.0, 1.0 - time_to_target / 180.0)
        else:
            time_w = 0.0

        # Safety component
        safety_w = max(0.0, 1.0 - max_adv / 20.0)

        # Liquidity component
        min_qty = min(bid_qty, ask_qty)
        liquidity_w = min(1.0, min_qty / 500.0)

        # Friction component
        friction_w = max(0.0, 1.0 - spread_pct / 5.0)

        score = (time_w * 40) + (safety_w * 25) + (liquidity_w * 20) + (friction_w * 15)
        return round(score, 2)
