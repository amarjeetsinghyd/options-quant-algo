import sys
import os
import time
from datetime import datetime
import threading

# Add root directory to python path if run as script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.utils.logger import get_logger

logger = get_logger("maintenance_service")

class MaintenanceService:
    def __init__(self):
        self._stop_event = threading.Event()
        self.last_run_date = None

    def _run_eod_tasks(self):
        logger.info("=== STARTING 3:35 PM EOD MAINTENANCE ===")
        try:
            # 1. Run Parquet Archiver (direct import — no subprocess path issues)
            logger.info("Running Parquet Archiver...")
            from src.utils.parquet_archiver import archive_ml_database, compress_institutional_memory
            archive_ml_database()
            compress_institutional_memory()

            # 2. Run Nightly Validator (direct import — no subprocess path issues)
            logger.info("Running ML Data Validator...")
            try:
                from src.ml_engine.eod_validator import run_eod_validation
                run_eod_validation()
            except ImportError:
                logger.warning("eod_validator not found or run_eod_validation() not exported — skipping.")
            except Exception as ev:
                logger.error(f"EOD Validator error: {ev}")

            # 3. Cloud Backup (direct call — no subprocess overhead)
            logger.info("Running Cloud Backup...")
            from src.services.cloud_backup import run_backup
            run_backup()

            logger.info("=== EOD MAINTENANCE COMPLETED ===")
        except Exception as e:
            logger.error(f"Error during EOD maintenance: {e}")


    def run(self):
        logger.info("Maintenance Service Started. Monitoring for 15:35 schedule...")
        
        while not self._stop_event.is_set():
            now = datetime.now()
            
            # Check if it's 15:35 (3:35 PM) and we haven't run today
            if now.hour == 15 and now.minute == 35:
                today_str = now.strftime("%Y-%m-%d")
                if self.last_run_date != today_str:
                    self._run_eod_tasks()
                    self.last_run_date = today_str
            
            # Sleep for 30 seconds before checking again
            time.sleep(30)

    def stop(self):
        logger.info("Maintenance Service stopping...")
        self._stop_event.set()

def main():
    service = MaintenanceService()
    try:
        service.run()
    except KeyboardInterrupt:
        service.stop()

if __name__ == "__main__":
    main()
