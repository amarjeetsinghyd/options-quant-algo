import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# Add root directory to python path if run as script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.broker import get_broker_adapter
from src.core.data_fetcher import DataFetcher
from src.config.engineering_config import DATA_DIR
from src.utils.logger import get_logger
from src.utils.market_calendar import is_trading_day

logger = get_logger("gap_fill_service")

CACHE_DIR = Path(DATA_DIR) / "gap_fill_cache"
CACHE_FILE = CACHE_DIR / "synthetic_volume_boot.parquet"


def load_cached_boot_dataframe() -> Optional[pd.DataFrame]:
    if not CACHE_FILE.exists():
        return None

    try:
        df = pd.read_parquet(CACHE_FILE)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        return df
    except Exception as e:
        logger.warning(f"[GapFillService] Failed to load cached boot data: {e}")
        return None


def is_cache_current() -> bool:
    if not CACHE_FILE.exists():
        return False

    try:
        modified_date = datetime.fromtimestamp(CACHE_FILE.stat().st_mtime).date()
        return modified_date == datetime.now().date()
    except Exception as e:
        logger.warning(f"[GapFillService] Could not determine cache staleness: {e}")
        return False


class GapFillService:
    def __init__(self):
        self._stop_event = threading.Event()
        self._last_run_date = None

        try:
            # Initialise the broker abstraction and obtain the underlying API.
            broker = get_broker_adapter()
            self.api = getattr(broker, "api", None)
            self.fetcher = DataFetcher(self.api)
        except Exception as e:
            logger.critical(f"[GapFillService] Failed to initialize broker adapter: {e}")
            raise

        self.cache_dir = CACHE_DIR
        self.cache_file = CACHE_FILE
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def is_cache_current(self) -> bool:
        return is_cache_current()

    def load_cached_boot_dataframe(self) -> Optional[pd.DataFrame]:
        return load_cached_boot_dataframe()

    def build_gap_fill_cache(self, days_back: int = 5) -> Path:
        logger.info("[GapFillService] Starting synthetic volume gap-fill build...")
        gap_fill_df = self.fetcher.get_historical_candles_with_synthetic_volume(days_back=days_back)

        if gap_fill_df is None or gap_fill_df.empty:
            raise RuntimeError("Gap fill fetch returned no data; aborting cache build.")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        gap_fill_df.to_parquet(self.cache_file, index=False, compression="ZSTD")
        logger.info(f"[GapFillService] Successfully wrote gap fill cache: {self.cache_file}")
        return self.cache_file

    def run_gap_fill(self, days_back: int = 5):
        if self.is_cache_current():
            logger.info("[GapFillService] Cache already current for today. Skipping gap fill.")
            self._last_run_date = datetime.now().date()
            return

        try:
            self.build_gap_fill_cache(days_back=days_back)
            self._last_run_date = datetime.now().date()
        except Exception as e:
            logger.error(f"[GapFillService] Gap fill failed: {e}")

    def _should_run(self, now: datetime) -> bool:
        if self._stop_event.is_set():
            return False

        if not is_trading_day(now):
            return False

        if self.is_cache_current():
            return False

        if now.hour == 15 and now.minute >= 35:
            return True

        if now.hour >= 16:
            return True

        return False

    def run(self):
        logger.info("=== STARTING GAP FILL SERVICE ===")
        while not self._stop_event.is_set():
            try:
                now = datetime.now()
                if self._should_run(now):
                    logger.info("[GapFillService] Scheduled gap fill window reached.")
                    self.run_gap_fill()
            except Exception as e:
                logger.error(f"[GapFillService] Error during run loop: {e}")
            time.sleep(30)

    def stop(self):
        logger.info("[GapFillService] Stopping service...")
        self._stop_event.set()


def run_gap_fill(days_back: int = 5):
    service = GapFillService()
    service.run_gap_fill(days_back=days_back)


def main():
    service = GapFillService()
    try:
        service.run()
    except KeyboardInterrupt:
        service.stop()


if __name__ == '__main__':
    main()
