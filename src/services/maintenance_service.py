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
            # 1. Gap Fill patches incomplete records
            logger.info("[EOD Step 1] Running EOD Gap Fill Service...")
            try:
                from src.services.gap_fill_service import run_gap_fill
                run_gap_fill(days_back=5)
            except Exception as gap_exc:
                logger.error(f"Gap Fill Service error: {gap_exc}")

            # 2. Indicator Audit & Data Certification
            logger.info("[EOD Step 2] Running Data Certification Audit...")
            try:
                from src.services.indicator_audit_service import run_daily_audit
                run_daily_audit()
            except Exception as audit_exc:
                logger.error(f"Data Certification Audit error: {audit_exc}")

            # 3. Generate Daily Summary
            logger.info("[EOD Step 3] Generating EOD Daily Summary...")
            try:
                from src.utils.summary_generator import generate_daily_summary
                generate_daily_summary()
            except Exception as sum_exc:
                logger.error(f"EOD Summary Generator error: {sum_exc}")

            # 4. Parquet Archival & Data Compression
            logger.info("[EOD Step 4] Compressing Parquet Data Lake...")
            try:
                from src.utils.parquet_archiver import archive_ml_database, compress_institutional_memory
                archive_ml_database()
                compress_institutional_memory()
            except Exception as arch_exc:
                logger.error(f"Parquet Archiver error: {arch_exc}")

            # 5. ML Data Validation
            logger.info("[EOD Step 5] Running ML Data Validation...")
            try:
                from src.ml_engine.eod_validator import run_eod_validation
                run_eod_validation()
            except ImportError:
                logger.warning("eod_validator not found or run_eod_validation() not exported — skipping.")
            except Exception as ev:
                logger.error(f"EOD Validator error: {ev}")

            # 6. Cloud Backup of certified data & summaries
            logger.info("[EOD Step 6] Running Cloud Backup...")
            try:
                from src.services.cloud_backup import run_backup
                run_backup()
            except Exception as backup_exc:
                logger.error(f"Cloud Backup error: {backup_exc}")

            # 7. Instrument Registry Synchronization
            logger.info("[EOD Step 7] Running EOD Instrument Registry Sync...")
            try:
                from src.services.instrument_sync_service import run_sync
                run_sync()
            except Exception as sync_exc:
                logger.error(f"EOD Instrument Sync error: {sync_exc}")

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
