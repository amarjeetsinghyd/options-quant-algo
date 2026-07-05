import os
import json
import threading
import time
from datetime import datetime
from src.core.message_bus import MessageBusSubscriber, EXEC_PORT
from src.utils.logger import get_logger
from src.utils.file_utils import write_json_atomic

logger = get_logger("telemetry_aggregator")

class RuntimeTelemetryAggregator:
    """
    Lightweight runtime component started by start_all.py.
    Listens to ZMQ events (EXEC.TELEMETRY, EXEC.ACTIVE_TRADE, EXEC.SETUP,
    EXEC.SIGNAL_RESOLVED, EXEC.DECISION) and aggregates the state atomically into
    runtime/dashboard_snapshot.json.
    """
    def __init__(self):
        self._stop_event = threading.Event()
        self.state_lock = threading.Lock()
        
        self.snapshot_file = os.path.join("runtime", "dashboard_snapshot.json")
        self.trade_history_file = os.path.join("data", "trades", "trade_history.json")
        
        # Load trade history if available on start
        history_data = []
        if os.path.exists(self.trade_history_file):
            try:
                with open(self.trade_history_file, 'r', encoding='utf-8') as f:
                    history_data = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load trade history: {e}")
                
        # Initialize internal state cache
        self.state = {
            "status": "running",
            "error_msg": "",
            "telemetry": {},
            "active_trade": None,
            "history": history_data,
            "decisions": [],
            "last_update": None
        }
        
        # Load last snapshot to preserve decisions/telemetry if it exists (avoids black holes on process restarts)
        if os.path.exists(self.snapshot_file):
            try:
                with open(self.snapshot_file, 'r', encoding='utf-8') as f:
                    snapshot = json.load(f)
                    with self.state_lock:
                        if snapshot.get("telemetry"):
                            self.state["telemetry"] = snapshot["telemetry"]
                        if snapshot.get("active_trade"):
                            self.state["active_trade"] = snapshot["active_trade"]
                        if snapshot.get("decisions"):
                            self.state["decisions"] = snapshot["decisions"]
                        if snapshot.get("last_update"):
                            self.state["last_update"] = snapshot["last_update"]
            except Exception as e:
                logger.warning(f"Could not recover dashboard snapshot: {e}")
        
        self.subscriber = None
        self.listener_thread = None
        self.writer_thread = None

    def start(self):
        """Starts background listener and periodic persistence loops."""
        logger.info("Starting RuntimeTelemetryAggregator...")
        self._stop_event.clear()
        
        # ZMQ subscriber setup
        self.subscriber = MessageBusSubscriber(EXEC_PORT, topics=["EXEC."])
        
        # ZMQ message receiver thread
        self.listener_thread = threading.Thread(target=self._zmq_loop, name="TelemetryZmqListener", daemon=True)
        self.listener_thread.start()
        
        # Periodic atomic writer thread
        self.writer_thread = threading.Thread(target=self._writer_loop, name="TelemetrySnapshotWriter", daemon=True)
        self.writer_thread.start()

    def _zmq_loop(self):
        """ZeroMQ listener loop."""
        try:
            self.subscriber.listen(self._on_message)
        except Exception as e:
            logger.error(f"ZMQ Subscriber error in aggregator: {e}")

    def _on_message(self, topic: str, payload: dict):
        """Processes execution bus ZMQ updates."""
        with self.state_lock:
            self.state["last_update"] = datetime.now().isoformat()
            
            if topic == "EXEC.TELEMETRY":
                if isinstance(self.state["telemetry"], dict) and isinstance(payload, dict):
                    self.state["telemetry"].update(payload)
                else:
                    self.state["telemetry"] = payload
                
            elif topic == "EXEC.ACTIVE_TRADE":
                self.state["active_trade"] = payload
                
            elif topic == "EXEC.SETUP":
                self.state["active_trade"] = payload
                
            elif topic == "EXEC.SIGNAL_RESOLVED":
                signal = payload.get("signal", {})
                if signal.get('signal_category') == 'EXECUTED':
                    # Prepend executed trade to history log cache
                    self.state["history"].insert(0, signal)
                    self.state["active_trade"] = None
                elif signal.get('signal_category') == 'REJECTED':
                    self.state["active_trade"] = None
                    
            elif topic == "EXEC.DECISION":
                self.state["decisions"].insert(0, payload)
                if len(self.state["decisions"]) > 100:
                    self.state["decisions"] = self.state["decisions"][:100]

    def _writer_loop(self):
        """Writes snapshot to disk atomically every 2 seconds."""
        while not self._stop_event.is_set():
            try:
                with self.state_lock:
                    snapshot_copy = json.loads(json.dumps(self.state)) # Deep copy state safely
                write_json_atomic(self.snapshot_file, snapshot_copy)
            except Exception as e:
                logger.error(f"Error persisting dashboard snapshot: {e}")
            time.sleep(2)

    def stop(self):
        """Stops ZMQ listener and writer threads gracefully."""
        logger.info("Stopping RuntimeTelemetryAggregator...")
        self._stop_event.set()
        if self.subscriber:
            try:
                self.subscriber.close()
            except Exception as e:
                logger.warning(f"Error closing ZMQ subscriber: {e}")
        
        # Write final snapshot state before closing
        try:
            with self.state_lock:
                snapshot_copy = json.loads(json.dumps(self.state))
            write_json_atomic(self.snapshot_file, snapshot_copy)
        except Exception:
            pass

        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=1.0)
        if self.writer_thread and self.writer_thread.is_alive():
            self.writer_thread.join(timeout=1.0)
        logger.info("RuntimeTelemetryAggregator stopped.")
