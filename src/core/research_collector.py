import os
import time
import threading
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

from src.utils.logger import get_logger
from src.core.session_manager import SessionManager
from src.core.data_fetcher import DataFetcher

logger = get_logger("research_collector")

# ── Storage config ──────────────────────────────────────────────────────────
RESEARCH_DIR = Path("data/research")
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

# ── Instruments to collect (token, symbol, exchange) ────────────────────────
DEFAULT_INSTRUMENTS = [
    {"token": "99926000", "symbol": "Nifty 50",    "exchange": "NSE"},
    {"token": "99926009", "symbol": "Nifty Bank",  "exchange": "NSE"},
    {"token": "26000",    "symbol": "NIFTY-I",     "exchange": "NFO"},
]

# ── Timeframes to archive ────────────────────────────────────────────────────
TIMEFRAMES = ["ONE_MINUTE", "FIVE_MINUTE", "FIFTEEN_MINUTE"]


class ResearchCollector:
    """
    Background service that collects OHLCV candle data for configured
    instruments and persists it as Parquet files partitioned by date.

    Directory layout:
        data/research/<symbol>/<timeframe>/<YYYY-MM-DD>.parquet

    Each run appends only NEW candles (dedup by timestamp).
    """

    def __init__(
        self,
        session_manager: SessionManager,
        instruments: list = None,
        timeframes: list = None,
        lookback_days: int = 5,
        poll_interval_seconds: int = 60,
    ):
        self.session_manager = session_manager
        self.instruments = instruments or DEFAULT_INSTRUMENTS
        self.timeframes = timeframes or TIMEFRAMES
        self.lookback_days = lookback_days
        self.poll_interval = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self):
        """Launch the collector in a daemon thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("ResearchCollector already running.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="ResearchCollector", daemon=True
        )
        self._thread.start()
        logger.info("ResearchCollector started (poll_interval=%ds).", self.poll_interval)

    def stop(self):
        """Signal the loop to stop and wait for clean exit."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=30)
        logger.info("ResearchCollector stopped.")

    # ── Internal loop ─────────────────────────────────────────────────────────

    def _run_loop(self):
        while not self._stop_event.is_set():
            try:
                self._collect_all()
            except Exception as exc:
                logger.error("ResearchCollector cycle error: %s", exc, exc_info=True)
            self._stop_event.wait(timeout=self.poll_interval)

    def _collect_all(self):
        smart_api = self.session_manager.get_api()
        if smart_api is None:
            logger.warning("No active SmartAPI session — skipping collection cycle.")
            return

        fetcher = DataFetcher(smart_api)
        to_date = datetime.now()
        from_date = to_date - timedelta(days=self.lookback_days)

        for instrument in self.instruments:
            for tf in self.timeframes:
                try:
                    self._collect_instrument(fetcher, instrument, tf, from_date, to_date)
                except Exception as exc:
                    logger.error(
                        "Failed collecting %s/%s: %s",
                        instrument["symbol"], tf, exc, exc_info=True,
                    )

    def _collect_instrument(
        self,
        fetcher: DataFetcher,
        instrument: dict,
        timeframe: str,
        from_date: datetime,
        to_date: datetime,
    ):
        symbol   = instrument["symbol"]
        token    = instrument["token"]
        exchange = instrument["exchange"]

        candles = fetcher.get_candle_data(
            exchange=exchange,
            symbol_token=token,
            interval=timeframe,
            from_date=from_date.strftime("%Y-%m-%d %H:%M"),
            to_date=to_date.strftime("%Y-%m-%d %H:%M"),
        )

        if candles is None or candles.empty:
            logger.debug("No candles returned for %s/%s.", symbol, timeframe)
            return

        self._persist(candles, symbol, timeframe)

    # ── Persistence helpers ──────────────────────────────────────────────────

    def _persist(self, new_df: pd.DataFrame, symbol: str, timeframe: str):
        """Append new candles to date-partitioned Parquet files."""
        # Ensure timestamp column exists and is datetime
        if "timestamp" not in new_df.columns:
            logger.warning("DataFrame missing 'timestamp' column; skipping persist.")
            return

        new_df["timestamp"] = pd.to_datetime(new_df["timestamp"])
        new_df = new_df.sort_values("timestamp")

        # Group by date and write per-day Parquet
        for date_str, day_df in new_df.groupby(new_df["timestamp"].dt.date):
            parquet_path = self._parquet_path(symbol, timeframe, str(date_str))
            day_df = self._merge_with_existing(parquet_path, day_df)
            day_df.to_parquet(parquet_path, index=False, compression="snappy")
            logger.debug("Persisted %d rows → %s", len(day_df), parquet_path)

    def _parquet_path(self, symbol: str, timeframe: str, date_str: str) -> Path:
        safe_symbol = symbol.replace(" ", "_").replace("/", "-")
        path = RESEARCH_DIR / safe_symbol / timeframe / f"{date_str}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _merge_with_existing(path: Path, new_df: pd.DataFrame) -> pd.DataFrame:
        """Read existing Parquet (if any), append new rows, dedup by timestamp."""
        if path.exists():
            try:
                existing = pd.read_parquet(path)
                combined = pd.concat([existing, new_df], ignore_index=True)
                combined["timestamp"] = pd.to_datetime(combined["timestamp"])
                combined = combined.drop_duplicates(subset="timestamp").sort_values("timestamp")
                return combined.reset_index(drop=True)
            except Exception as exc:
                logger.warning("Could not merge existing parquet %s: %s", path, exc)
        return new_df.reset_index(drop=True)

    # ── Utility: load archived data ──────────────────────────────────────────

    @staticmethod
    def load(
        symbol: str,
        timeframe: str,
        start_date: str = None,
        end_date: str = None,
    ) -> pd.DataFrame:
        """
        Load archived Parquet data for a symbol/timeframe.
        Optionally filter by start_date / end_date (YYYY-MM-DD strings).
        """
        safe_symbol = symbol.replace(" ", "_").replace("/", "-")
        base = RESEARCH_DIR / safe_symbol / timeframe
        if not base.exists():
            logger.warning("No archived data found at %s", base)
            return pd.DataFrame()

        files = sorted(base.glob("*.parquet"))
        if not files:
            return pd.DataFrame()

        frames = []
        for f in files:
            date_tag = f.stem  # YYYY-MM-DD
            if start_date and date_tag < start_date:
                continue
            if end_date and date_tag > end_date:
                continue
            try:
                frames.append(pd.read_parquet(f))
            except Exception as exc:
                logger.warning("Skipping corrupt parquet %s: %s", f, exc)

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        return df.sort_values("timestamp").reset_index(drop=True)
