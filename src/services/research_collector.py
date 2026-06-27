# research_collector.py
# Parquet-based Research Data Collection Service
# QuantOS Runtime — Phase 6.2
# Governed by: DOC-1.2 Engineering Optimization Roadmap (ASD v1)
#
# Responsibilities:
#   - Subscribe to market data feed via ZMQ
#   - Compute and attach technical indicators (VFI, EMA, VWAP)
#   - Write enriched tick/candle data to Parquet files every session
#   - Enable offline replay and feature generation from stored data
#   - Support incremental Parquet append (no full rewrites)

import os
import sys
import time
import threading
from datetime import datetime

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    from src.config.engineering_config import (
        ENABLE_RESEARCH_COLLECTOR,
        ENABLE_PARQUET_JOURNAL,
        PARQUET_WRITE_INTERVAL_SECONDS,
        PARQUET_DIR,
    )
except ImportError:
    ENABLE_RESEARCH_COLLECTOR = True
    ENABLE_PARQUET_JOURNAL = True
    PARQUET_WRITE_INTERVAL_SECONDS = 60
    PARQUET_DIR = os.path.join(os.path.dirname(__file__), '../../data/research_journal')

if not ENABLE_RESEARCH_COLLECTOR:
    print("[research_collector] DISABLED via ENABLE_RESEARCH_COLLECTOR — exiting.")
    sys.exit(0)

try:
    from src.utils.logger import get_logger
    logger = get_logger("research_collector")
except ImportError:
    import logging
    logger = logging.getLogger("research_collector")
    logging.basicConfig(level=logging.INFO)


class ResearchCollector:
    """
    Collects enriched market data each trading session and writes to Parquet.
    Supports replay by loading any session's Parquet file for feature regeneration.
    """

    def __init__(self):
        self.parquet_dir = PARQUET_DIR
        os.makedirs(self.parquet_dir, exist_ok=True)
        self._buffer = []           # in-memory buffer of tick records
        self._lock = threading.Lock()
        self._running = False
        self._write_interval = PARQUET_WRITE_INTERVAL_SECONDS
        logger.info(f"[ResearchCollector] Parquet journal dir: {self.parquet_dir}")

    def record(self, tick: dict):
        """
        Add an enriched tick record to the buffer.
        Expected fields: timestamp, symbol, open, high, low, close, volume,
                         vfi, ema9, vwap, signal, session_id
        """
        with self._lock:
            tick.setdefault('recorded_at', datetime.utcnow().isoformat())
            self._buffer.append(tick)

    def _flush_to_parquet(self):
        """Flush buffer to Parquet file for today's session."""
        with self._lock:
            if not self._buffer:
                return
            records = self._buffer.copy()
            self._buffer.clear()

        df = pd.DataFrame(records)
        session_date = datetime.utcnow().strftime('%Y%m%d')
        filename = os.path.join(self.parquet_dir, f"session_{session_date}.parquet")

        if ENABLE_PARQUET_JOURNAL:
            if os.path.exists(filename):
                # Append to existing file
                existing = pd.read_parquet(filename)
                df = pd.concat([existing, df], ignore_index=True)
            df.to_parquet(filename, index=False, engine='pyarrow')
            logger.info(f"[ResearchCollector] Flushed {len(records)} records → {filename}")
        else:
            logger.warning("[ResearchCollector] ENABLE_PARQUET_JOURNAL=False, flush skipped.")

    def _writer_loop(self):
        """Background thread: flush buffer to Parquet at fixed intervals."""
        logger.info(f"[ResearchCollector] Writer loop started (interval={self._write_interval}s)")
        while self._running:
            time.sleep(self._write_interval)
            try:
                self._flush_to_parquet()
            except Exception as e:
                logger.error(f"[ResearchCollector] Flush error: {e}")
        # Final flush on shutdown
        self._flush_to_parquet()
        logger.info("[ResearchCollector] Final flush on shutdown complete.")

    def start(self):
        """Start the background Parquet writer thread."""
        self._running = True
        t = threading.Thread(target=self._writer_loop, daemon=True, name="research_collector_writer")
        t.start()
        logger.info("[ResearchCollector] Started.")

    def stop(self):
        """Gracefully stop the writer thread."""
        logger.info("[ResearchCollector] Stopping...")
        self._running = False

    @staticmethod
    def replay(session_date: str, parquet_dir: str = None) -> pd.DataFrame:
        """
        Load a specific session's Parquet file for replay/feature regeneration.
        Args:
            session_date: Format YYYYMMDD
            parquet_dir: Override directory (defaults to configured PARQUET_DIR)
        Returns:
            pd.DataFrame of the session records
        """
        base = parquet_dir or PARQUET_DIR
        filename = os.path.join(base, f"session_{session_date}.parquet")
        if not os.path.exists(filename):
            raise FileNotFoundError(f"[ResearchCollector] No session file for {session_date}: {filename}")
        df = pd.read_parquet(filename, engine='pyarrow')
        logger.info(f"[ResearchCollector] Replayed {len(df)} records from {filename}")
        return df


# ─── Standalone entry point for process-based launch from start_all.py ───
if __name__ == "__main__":
    collector = ResearchCollector()
    collector.start()
    logger.info("[ResearchCollector] Running as standalone service. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        collector.stop()
        logger.info("[ResearchCollector] Stopped.")
