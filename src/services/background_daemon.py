import sys
import os
import threading
import time
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.utils.logger import get_logger

# Import the standalone background services
from src.services.health_service import PassiveHealthMonitor
from src.services.decision_journal import DecisionJournal
from src.services.cloud_backup import run_scheduler as run_cloud_backup
from src.services.maintenance_service import MaintenanceService
from src.services.opportunity_tracker import OpportunityTracker
from src.services.shadow_service import ShadowService
from src.config.engineering_config import ENABLE_SHADOW_SERVICE

logger = get_logger("background_daemon")

def run_service(service_name, target):
    """Wrapper to run a service in a thread and catch exceptions."""
    try:
        logger.info(f"Starting {service_name} within background daemon...")
        target()
    except Exception as e:
        logger.error(f"Error in {service_name}: {e}", exc_info=True)

class BackgroundDaemon:
    """
    Consolidates multiple lightweight background tasks into a single Python process 
    to drastically reduce memory overhead on 1GB RAM instances.
    """
    def __init__(self):
        self.threads = []
        
        # Instantiate services
        self.health_monitor = PassiveHealthMonitor()
        self.decision_journal = DecisionJournal()
        self.maintenance_service = MaintenanceService()
        self.opportunity_tracker = OpportunityTracker()
        
        if ENABLE_SHADOW_SERVICE:
            self.shadow_service = ShadowService()
        else:
            self.shadow_service = None

    def start(self):
        logger.info("Initializing Lean Background Daemon (Memory Optimization Mode)")

        # Create thread targets
        targets = [
            ("PassiveHealthMonitor", self.health_monitor.start),
            ("DecisionJournal", self.decision_journal.start),
            ("MaintenanceService", self.maintenance_service.run),
            ("OpportunityTracker", self.opportunity_tracker.start)
        ]

        if self.shadow_service:
            targets.append(("ShadowService", self.shadow_service.start))

        # Launch all targets in separate daemon threads
        for name, func in targets:
            t = threading.Thread(target=run_service, args=(name, func), daemon=True)
            self.threads.append(t)
            t.start()

        # Keep the main thread alive so daemon threads don't instantly exit
        try:
            while True:
                time.sleep(60) # Extreme survival mode: Wake up only once a minute
        except KeyboardInterrupt:
            logger.info("Background Daemon shutting down...")

if __name__ == "__main__":
    daemon = BackgroundDaemon()
    daemon.start()
