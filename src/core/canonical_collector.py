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
from src.core.message_bus import MessageBusSubscriber, FEED_PORT
from src.core.dataset_manifest import DatasetManifest

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
        self._thread = None
        self._zmq_thread = None
        
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
        logger.info(f"=== Canonical Observation Collector v3.1 Started ===")

    def stop(self):
        logger.info("CanonicalCollector stopping...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=30)
        self.sub.close()
        logger.info("CanonicalCollector stopped.")

    def _get_category(self, token: str, symbol: str) -> str:
        symbol = str(symbol).upper()
        if symbol.endswith("CE") or symbol.endswith("PE"):
            return "options"
        elif symbol.endswith("FUT"):
            return "futures"
        elif token in ["26000", "26009"]: # NIFTY, BANKNIFTY spot
            return "underlying"
        else:
            return "constituents"

    def _listen_zmq(self):
        def on_tick(topic, payload):
            if not self._stop_event.is_set():
                now = datetime.now()
                payload['local_observation_timestamp'] = now.isoformat() + "Z"
                
                token = str(payload.get('token', ''))
                symbol = payload.get('symbol', '')
                if not symbol:
                    # In some feeds symbol isn't provided directly, infer category best effort
                    category = "options" if int(token) > 30000 else "constituents"
                    if token == "26000": category = "underlying"
                else:
                    category = self._get_category(token, symbol)
                
                with self._buffer_lock:
                    # 1. Store Raw Tick
                    self._raw_buffers[category].append(payload)
                    
                    # 2. Update Live Canonical State
                    ltp = float(payload.get('last_traded_price', 0) / 100.0) if payload.get('last_traded_price') else 0.0
                    vol = payload.get('volume_trade_for_the_day', 0)
                    
                    if token not in self.market_state[category]:
                        self.market_state[category][token] = {
                            "symbol": symbol,
                            "open": ltp,
                            "high": ltp,
                            "low": ltp,
                            "close": ltp,
                            "volume_for_the_day": vol
                        }
                    else:
                        state = self.market_state[category][token]
                        state["close"] = ltp
                        state["volume_for_the_day"] = max(state["volume_for_the_day"], vol)
                        if ltp > state["high"]: state["high"] = ltp
                        if ltp > 0 and ltp < state["low"]: state["low"] = ltp
                        
                    # Option Specific Microstructure
                    if category == "options":
                        state = self.market_state[category][token]
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
                for tk in self.market_state[cat]:
                    last_close = self.market_state[cat][tk]["close"]
                    self.market_state[cat][tk]["open"] = last_close
                    self.market_state[cat][tk]["high"] = last_close
                    self.market_state[cat][tk]["low"] = last_close

        obs_uuid = str(uuid.uuid4())
        date_str = timestamp.strftime("%Y/%m/%d")
        time_str = timestamp.strftime("%H:%M:00") # Lock to the minute boundary
        
        for category, tokens in snapshot.items():
            if not tokens: continue
            
            records = []
            for tk, data in tokens.items():
                record = data.copy()
                record["token"] = tk
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
