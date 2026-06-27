import os
import sys
from datetime import datetime
from pathlib import Path

# Add root directory to python path if run as script
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from src.core.dataset_health_monitor import DatasetHealthMonitor
from src.utils.logger import get_logger

logger = get_logger("eod_health_check")

def run_eod_check():
    """
    Runs the End-Of-Day Health Scan on today's Canonical Observations.
    Should be scheduled via CRON or Task Scheduler at 15:45 PM.
    """
    logger.info("=== Starting EOD Dataset Health Scan ===")
    
    today = datetime.now()
    date_str = today.strftime("%Y/%m/%d")
    
    base_dir = Path("data/institutional_memory/canonical_observations")
    
    categories = ["options_state", "constituents_state", "underlying_state", "futures_state"]
    
    all_healthy = True
    
    for category in categories:
        target_dir = base_dir / category / date_str
        if target_dir.exists():
            logger.info(f"Scanning partition: {target_dir}")
            is_healthy = DatasetHealthMonitor.verify_daily_partition(target_dir, today.strftime("%Y-%m-%d"))
            if not is_healthy:
                all_healthy = False
        else:
            logger.info(f"Skipping {category}: Directory does not exist yet ({target_dir})")
            
    if all_healthy:
        logger.info("=== EOD Scan Complete. ALL PARTITIONS HEALTHY. ===")
    else:
        logger.critical("=== EOD Scan Complete. CORRUPTION OR MISSING DATA DETECTED. Check logs. ===")

if __name__ == "__main__":
    run_eod_check()
