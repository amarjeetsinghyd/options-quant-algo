import sys
import os
import time
import subprocess
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
            # 1. Run Parquet Archiver
            logger.info("Running Parquet Archiver...")
            subprocess.run([sys.executable, "src/utils/parquet_archiver.py"], check=False)
            
            # 2. Run Nightly Validator
            logger.info("Running ML Data Validator...")
            subprocess.run([sys.executable, "src/ml_engine/eod_validator.py"], check=False)
            
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
