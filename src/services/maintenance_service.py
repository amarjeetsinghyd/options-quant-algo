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

    def publish_notification(self, event_type, severity, title, description):
        pub = None
        try:
            import uuid
            from src.utils.provenance import get_provenance_metadata
            try:
                git_commit = get_provenance_metadata().get("git_commit", "unknown")[:7]
            except Exception:
                git_commit = "unknown"
                
            envelope = {
                "schema_version": "1.0",
                "generated_at": datetime.utcnow().isoformat() + "Z",
                "engine_version": "1.1.0",
                "git_commit": git_commit,
                "event": {
                    "notification_id": str(uuid.uuid4()),
                    "event_type": event_type,
                    "severity": severity,
                    "title": title,
                    "description": description,
                    "timestamp": int(time.time() * 1000),
                    "correlation_id": "",
                    "strategy": "--",
                    "instrument": "--",
                    "premium": None,
                    "pnl": None,
                    "status": "Generated"
                }
            }
            from src.core.message_bus import MessageBusPublisher, EXEC_PORT
            pub = MessageBusPublisher(EXEC_PORT)
            time.sleep(0.1) # brief pause to ensure ZMQ bind is ready
            pub.publish("EXEC.EVENT", envelope)
            time.sleep(0.1) # brief pause to flush
        except Exception as e:
            logger.error(f"[MaintenanceService] Failed to publish notification: {e}")
        finally:
            if pub:
                try:
                    pub.close()
                except Exception:
                    pass

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
            audit_confidence = 100.00
            try:
                from src.services.indicator_audit_service import run_daily_audit
                report = run_daily_audit()
                if report:
                    audit_confidence = float(report.get("confidence_score", 100.00))
                    if report.get("research_certification") == "FAILED":
                        self.publish_notification(
                            event_type="CERTIFICATION_FAILED",
                            severity="ERROR",
                            title="Certification Failed",
                            description=f"Daily Data Certification Audit Failed for {report.get('market_date')}"
                        )
            except Exception as audit_exc:
                logger.error(f"Data Certification Audit error: {audit_exc}")
                self.publish_notification(
                    event_type="AUDIT_FAILED",
                    severity="ERROR",
                    title="Audit Failed",
                    description=f"Daily Data Certification Audit crashed: {audit_exc}"
                )

            # 3. Generate Daily Summary
            logger.info("[EOD Step 3] Generating EOD Daily Summary...")
            try:
                from src.utils.summary_generator import generate_daily_summary
                summary_data = generate_daily_summary()
                
                trade_metrics = summary_data.get("trade_metrics", {})
                dq = summary_data.get("data_quality", {})
                
                total_trades = trade_metrics.get("total_trades", 0)
                wins = trade_metrics.get("wins", 0)
                losses = trade_metrics.get("losses", 0)
                net_pl = trade_metrics.get("net_pl", 0.0)
                observations = dq.get("decisions_logged", 0)
                
                pnl_sign = "+" if net_pl >= 0 else ""
                eod_desc = (
                    f"Trades : {total_trades}\n"
                    f"Wins : {wins}\n"
                    f"Losses : {losses}\n\n"
                    f"PnL\n"
                    f"{pnl_sign}₹{net_pl:.2f}\n\n"
                    f"Research\n"
                    f"{observations} observations\n\n"
                    f"Confidence\n"
                    f"{audit_confidence:.2f}%"
                )
                
                self.publish_notification(
                    event_type="DAILY_SUMMARY_READY",
                    severity="SUCCESS",
                    title="Trading Day Complete",
                    description=eod_desc
                )
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
                self.publish_notification(
                    event_type="CLOUD_BACKUP_FAILED",
                    severity="ERROR",
                    title="Cloud Backup Failed",
                    description=f"Cloud backup failed to execute: {backup_exc}"
                )

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
