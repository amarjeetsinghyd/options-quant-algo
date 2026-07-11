import sys
import os
import time

# Add root directory to python path if run as script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.canonical_collector import CanonicalCollector
import threading
from src.utils.logger import get_logger

logger = get_logger("research_service")

def main():
    logger.info("=== STARTING INSTITUTIONAL CANONICAL COLLECTOR SERVICE v3.1 ===")
    
    # Start the background collector
    collector = CanonicalCollector(poll_interval_seconds=60)
    collector.start()
    
    stop_event = threading.Event()
    
    try:
        # Keep the main thread alive but responsive to shutdown
        while not stop_event.is_set():
            stop_event.wait(1)
    except KeyboardInterrupt:
        logger.info("Research Collector shutting down...")
        collector.stop()
        
if __name__ == "__main__":
    main()
