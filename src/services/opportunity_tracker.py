import sys
import os
import time
import json
import threading
from datetime import datetime
from collections import deque
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.message_bus import MessageBusSubscriber, FEED_PORT, EXEC_PORT
from src.utils.logger import get_logger

logger = get_logger("opportunity_tracker")

class OpportunityTracker:
    """
    Passively monitors ALL signals (Accepted and Rejected) for 60 minutes
    to calculate Maximum Favorable Excursion (MFE) and Maximum Adverse Excursion (MAE).
    Saves outcomes permanently to VPS for ML models and Dashboard UI.
    """
    def __init__(self, observation_minutes=60):
        self.observation_seconds = observation_minutes * 60
        
        self.active_signals = {}  # signal_uuid -> dict
        self.lock = threading.Lock()
        
        self.data_dir = Path("data/insights")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.outcomes_file = self.data_dir / "signal_outcomes.json"
        
        # In-memory outcomes for the dashboard
        self.outcomes = self._load_outcomes()
        
        # Listeners
        self.feed_sub = MessageBusSubscriber(FEED_PORT, topics=["TICK."])
        self.intel_sub = MessageBusSubscriber(EXEC_PORT, topics=["EXEC.DECISION"])
        
        self.stop_event = threading.Event()
        
    def _load_outcomes(self):
        if self.outcomes_file.exists():
            try:
                with open(self.outcomes_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading signal outcomes: {e}")
        return []
        
    def _save_outcomes(self):
        try:
            temp_file = str(self.outcomes_file) + ".tmp"
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.outcomes, f, indent=4)
            os.replace(temp_file, str(self.outcomes_file))
        except Exception as e:
            logger.error(f"Failed to save signal outcomes: {e}")

    def on_feed_tick(self, topic, payload):
        token = str(payload.get("token"))
        ltp = payload.get("ltp")
        if not token or not ltp:
            return
            
        with self.lock:
            # Update bounds for any active signal targeting this token
            for sig_id, data in self.active_signals.items():
                if data["token"] == token:
                    if ltp > data["highest_price"]:
                        data["highest_price"] = ltp
                    if ltp < data["lowest_price"]:
                        data["lowest_price"] = ltp
                        
    def on_decision(self, topic, payload):
        sig_id = payload.get("uuid")
        if not sig_id:
            return
            
        token = payload.get("token")
        price = payload.get("strike_price") or payload.get("underlying_price")
        if not token or not price:
            return
            
        # Register for tracking
        with self.lock:
            self.active_signals[sig_id] = {
                "uuid": sig_id,
                "token": str(token),
                "status": payload.get("status", "REJECTED"),
                "strategy": payload.get("strategy", "UNKNOWN"),
                "entry_price": float(price),
                "highest_price": float(price),
                "lowest_price": float(price),
                "start_time": time.time(),
                "human_reason": payload.get("human_reason", "")
            }
        logger.info(f"[Tracker] Registered new signal {sig_id} ({payload.get('status')}) for 60-min observation.")

    def _cleanup_loop(self):
        while not self.stop_event.is_set():
            time.sleep(10)
            now = time.time()
            completed = []
            
            with self.lock:
                for sig_id, data in list(self.active_signals.items()):
                    if now - data["start_time"] >= self.observation_seconds:
                        completed.append(data)
                        del self.active_signals[sig_id]
                        
                for data in completed:
                    # Calculate MFE / MAE %
                    ep = data["entry_price"]
                    mfe_pct = round(((data["highest_price"] - ep) / ep) * 100, 2)
                    mae_pct = round(((data["lowest_price"] - ep) / ep) * 100, 2)
                    
                    outcome_record = {
                        "uuid": data["uuid"],
                        "timestamp": datetime.now().isoformat(),
                        "strategy": data["strategy"],
                        "status": data["status"],
                        "entry_price": ep,
                        "highest_price": data["highest_price"],
                        "lowest_price": data["lowest_price"],
                        "mfe_pct": mfe_pct,
                        "mae_pct": mae_pct,
                        "human_reason": data["human_reason"]
                    }
                    self.outcomes.append(outcome_record)
                    logger.info(f"[Tracker] Signal {data['uuid']} finalized. Status: {data['status']}, MFE: {mfe_pct}%")
                    
                if completed:
                    self._save_outcomes()

    def start(self):
        logger.info("=== STARTING UNIFIED OPPORTUNITY TRACKER ===")
        threading.Thread(target=self.feed_sub.listen, args=(self.on_feed_tick,), daemon=True).start()
        threading.Thread(target=self.intel_sub.listen, args=(self.on_decision,), daemon=True).start()
        threading.Thread(target=self._cleanup_loop, daemon=True).start()
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop_event.set()
            logger.info("Opportunity Tracker stopped.")

if __name__ == "__main__":
    OpportunityTracker().start()
