import os
import time
import threading
import pandas as pd
from datetime import datetime
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from src.utils.logger import get_logger
from src.core.message_bus import MessageBusSubscriber, FEED_PORT

logger = get_logger("research_collector")

RESEARCH_DIR = Path("data/research/ticks")
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

class ResearchCollector:
    """
    Tick-by-Tick WebSocket Data Collector.
    Listens to FEED_PORT via ZeroMQ.
    Buffers incoming ticks in memory.
    Flushes to Parquet every 5 minutes.
    Partitioned by date: data/research/ticks/<YYYY-MM-DD>.parquet
    """

    def __init__(self, session_manager=None, poll_interval_seconds: int = 300):
        # session_manager kept for interface compatibility with research_service.py
        self.poll_interval = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread = None
        self._zmq_thread = None
        self._buffer = []
        self._buffer_lock = threading.Lock()
        
        self.sub = MessageBusSubscriber(FEED_PORT, topics=["TICK"])

    def start(self):
        if self._thread and self._thread.is_alive():
            logger.warning("ResearchCollector already running.")
            return
            
        self._stop_event.clear()
        
        # Start ZMQ listener in a separate thread
        self._zmq_thread = threading.Thread(target=self._listen_zmq, name="ResearchZMQ", daemon=True)
        self._zmq_thread.start()
        
        # Start Flusher thread
        self._thread = threading.Thread(target=self._run_loop, name="ResearchFlusher", daemon=True)
        self._thread.start()
        logger.info(f"Tick-by-Tick ResearchCollector started (flush interval={self.poll_interval}s).")

    def stop(self):
        logger.info("ResearchCollector stopping...")
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=30)
        self.sub.close()
        logger.info("ResearchCollector stopped.")

    def _listen_zmq(self):
        def on_tick(topic, payload):
            if not self._stop_event.is_set():
                # payload is the tick dict
                # add received timestamp
                payload['received_at'] = datetime.now().isoformat()
                with self._buffer_lock:
                    self._buffer.append(payload)
                    
        logger.info("[ResearchCollector] Listening to ZMQ FEED_PORT for ticks...")
        self.sub.listen(on_tick)

    def _run_loop(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self.poll_interval)
            if self._stop_event.is_set():
                break
            try:
                self._flush()
            except Exception as exc:
                logger.error("ResearchCollector flush error: %s", exc, exc_info=True)
        
        # Final flush on shutdown
        self._flush()

    def _flush(self):
        with self._buffer_lock:
            if not self._buffer:
                return
            records = self._buffer.copy()
            self._buffer.clear()
            
        df = pd.DataFrame(records)
        date_str = datetime.now().strftime("%Y-%m-%d")
        parquet_path = RESEARCH_DIR / f"{date_str}.parquet"
        
        # Deduplicate and Append
        if parquet_path.exists():
            try:
                existing = pd.read_parquet(parquet_path)
                combined = pd.concat([existing, df], ignore_index=True)
                # Ticks might not have 'timestamp' reliably from all sources, use received_at
                if "token" in combined.columns:
                    combined = combined.drop_duplicates(subset=["token", "received_at"]).sort_values("received_at")
                combined.to_parquet(parquet_path, index=False, compression="snappy")
            except Exception as e:
                logger.error(f"Error appending to parquet: {e}")
                # Fallback to saving as a new chunk
                chunk_path = RESEARCH_DIR / f"{date_str}_{int(time.time())}.parquet"
                df.to_parquet(chunk_path, index=False, compression="snappy")
        else:
            df.to_parquet(parquet_path, index=False, compression="snappy")
            
        logger.info(f"[ResearchCollector] Flushed {len(records)} ticks to {parquet_path}")
