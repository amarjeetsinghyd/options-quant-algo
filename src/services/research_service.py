import sys
import os
import time

# Add root directory to python path if run as script
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.session_manager import SessionManager
from src.core.canonical_collector import CanonicalCollector
from src.utils.logger import get_logger

logger = get_logger("research_service")

def main():
    logger.info("=== STARTING INSTITUTIONAL CANONICAL COLLECTOR SERVICE v3.1 ===")
    
    # Initialize session manager to handle Angel One auth
    session_manager = SessionManager()
    
    # Start the background collector
    collector = CanonicalCollector(session_manager=session_manager, poll_interval_seconds=60)
    collector.start()
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Research Collector shutting down...")
        collector.stop()
        
if __name__ == "__main__":
    main()
