import os
import sys
import time
import json
import threading
import pandas as pd
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.message_bus import MessageBusSubscriber, EXEC_PORT
from src.utils.logger import get_logger

logger = get_logger("decision_journal")

class DecisionJournal:
    def __init__(self):
        self.running = False
        self.sub = MessageBusSubscriber(EXEC_PORT, topics=["EXEC.DECISION", "EXEC.SIGNAL_RESOLVED"])
        
        self.data_dir = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../data')))
        self.parquet_path = self.data_dir / "decision_history.parquet"
        self.health_json = self.data_dir / "health_state.json"
        
        self.buffer = []
        self.lock = threading.Lock()
        
    def _flush_buffer(self):
        with self.lock:
            if not self.buffer:
                return
            df_new = pd.json_normalize(self.buffer)
            # Ensure timestamps are parsed properly
            if 'timestamp' in df_new.columns:
                df_new['timestamp'] = pd.to_datetime(df_new['timestamp'])
                
            if self.parquet_path.exists():
                try:
                    df_old = pd.read_parquet(self.parquet_path)
                    df_new = pd.concat([df_old, df_new], ignore_index=True)
                except Exception as e:
                    logger.error(f"Error reading existing parquet: {e}")
                    
            try:
                df_new.to_parquet(self.parquet_path, engine='pyarrow')
                logger.info(f"Flushed {len(self.buffer)} decisions to journal.")
                self.buffer = []
            except Exception as e:
                logger.error(f"Error writing to parquet: {e}")

    def _get_health_snapshot_uuid(self):
        if self.health_json.exists():
            try:
                with open(self.health_json, 'r') as f:
                    data = json.load(f)
                    latest = data.get("latest", {})
                    if "timestamp" in latest:
                        return f"health_{latest['timestamp']}"
            except:
                pass
        return "UNKNOWN_HEALTH"

    def _on_message(self, topic, message):
        if not isinstance(message, dict):
            return
            
        if topic == "EXEC.DECISION":
            message["health_snapshot_uuid"] = self._get_health_snapshot_uuid()
            
            if "machine_state" in message and isinstance(message["machine_state"], dict):
                message["machine_state_json"] = json.dumps(message["machine_state"])
                del message["machine_state"]
                
            if "market_state" in message and isinstance(message["market_state"], dict):
                message["market_state_json"] = json.dumps(message["market_state"])
                del message["market_state"]
            
            with self.lock:
                self.buffer.append(message)
                
            if len(self.buffer) >= 10:
                self._flush_buffer()
                
        elif topic == "EXEC.SIGNAL_RESOLVED":
            # Just append execution result
            if "signal" in message and message["signal"]:
                signal_data = message["signal"]
                decision_uuid = signal_data.get("decision_uuid", "UNKNOWN")
                resolution_payload = {
                    "decision_uuid": decision_uuid,
                    "timestamp": datetime.now().isoformat(),
                    "status": signal_data.get("signal_category", "UNKNOWN_RESOLUTION"),
                    "resolution_price": message.get("price", 0.0),
                    "is_execution_update": True
                }
                with self.lock:
                    self.buffer.append(resolution_payload)

    def start(self):
        self.running = True
        logger.info("=== Scientific Decision Journal Started ===")
        
        # Start MessageBusSubscriber blocking loop in thread
        listen_thread = threading.Thread(target=self.sub.listen, args=(self._on_message,), daemon=True)
        listen_thread.start()
        
        while self.running:
            time.sleep(60)
            self._flush_buffer()

if __name__ == "__main__":
    journal = DecisionJournal()
    try:
        journal.start()
    except KeyboardInterrupt:
        logger.info("Shutting down Decision Journal...")
        journal.running = False
        journal._flush_buffer()
        journal.sub.close()
