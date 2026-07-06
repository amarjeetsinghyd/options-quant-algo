import os
import json
import threading
import time
from datetime import datetime
from src.core.message_bus import MessageBusSubscriber, EXEC_PORT
from src.utils.logger import get_logger
from src.utils.file_utils import write_envelope_json_atomic

def get_notification_priority(event_type: str, description: str) -> str:
    evt = str(event_type).upper()
    desc = str(description).upper()
    
    # CRITICAL
    if any(x in evt for x in ["BUY_EXECUTED", "SELL_EXECUTED", "STOP_LOSS", "TARGET_HIT", "TIME_STOP", "FEED_OFFLINE"]):
        return "CRITICAL"
    if any(x in desc for x in ["BUY EXECUTED", "SELL EXECUTED", "STOP LOSS", "TARGET HIT", "TIME STOP", "FEED OFFLINE"]):
        return "CRITICAL"
        
    # HIGH
    if any(x in evt for x in ["BRAIN_RESTARTED", "RESEARCH_COMPLETED", "CERTIFICATION_FAILED"]):
        return "HIGH"
    if any(x in desc for x in ["BRAIN RESTART", "RESEARCH COMPLETED", "CERTIFICATION FAILED"]):
        return "HIGH"
        
    # NORMAL
    if any(x in evt for x in ["DAILY_SUMMARY_READY", "AUDIT_PASSED", "AUDIT_COMPLETED", "BACKUP_COMPLETED", "CLOUD_BACKUP_SUCCESS"]):
        return "NORMAL"
    if any(x in desc for x in ["DAILY SUMMARY", "AUDIT PASSED", "BACKUP COMPLETED", "CLOUD BACKUP SUCCESS"]):
        return "NORMAL"
        
    # LOW
    if any(x in evt for x in ["HEARTBEAT", "SERVICE_RESTART", "ROUTINE"]):
        return "LOW"
    if any(x in desc for x in ["HEARTBEAT", "SERVICE RESTART", "ROUTINE", "RESTARTED"]):
        return "LOW"
        
    return "LOW"

class RuntimeTelemetryAggregator:
    """
    Lightweight runtime component started by start_all.py.
    Listens to ZMQ events (EXEC.TELEMETRY, EXEC.ACTIVE_TRADE, EXEC.SETUP,
    EXEC.SIGNAL_RESOLVED, EXEC.DECISION, EXEC.TICK) and aggregates the state atomically into
    runtime/terminal_snapshot.json.
    """
    def __init__(self):
        self._stop_event = threading.Event()
        self.state_lock = threading.Lock()
        
        self.snapshot_file = os.path.join("runtime", "terminal_snapshot.json")
        self.trade_history_file = os.path.join("data", "trades", "trade_history.json")
        self.notification_history_file = os.path.join("runtime", "notification_history.json")
        
        # Load trade history if available on start
        history_data = []
        if os.path.exists(self.trade_history_file):
            try:
                with open(self.trade_history_file, 'r', encoding='utf-8') as f:
                    history_data = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load trade history: {e}")
                
        # Load notification history
        self.notification_history = []
        if os.path.exists(self.notification_history_file):
            try:
                with open(self.notification_history_file, 'r', encoding='utf-8') as f:
                    self.notification_history = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load notification history: {e}")
                
        # Initialize internal state cache
        self.state = {
            "status": "running",
            "error_msg": "",
            "telemetry": {},
            "active_trade": None,
            "history": history_data,
            "decisions": [],
            "last_ticks": [],
            "system_events": [],
            "last_update": None
        }
        
        # Load last snapshot to preserve decisions/telemetry if it exists (avoids black holes on process restarts)
        if os.path.exists(self.snapshot_file):
            try:
                with open(self.snapshot_file, 'r', encoding='utf-8') as f:
                    envelope = json.load(f)
                    snapshot = envelope.get("payload", {}) if "payload" in envelope else envelope
                    with self.state_lock:
                        if snapshot.get("telemetry"):
                            self.state["telemetry"] = snapshot["telemetry"]
                        if snapshot.get("active_trade"):
                            self.state["active_trade"] = snapshot["active_trade"]
                        if snapshot.get("decisions"):
                            self.state["decisions"] = snapshot["decisions"]
                        if snapshot.get("last_ticks"):
                            self.state["last_ticks"] = snapshot["last_ticks"]
                        if snapshot.get("system_events"):
                            self.state["system_events"] = snapshot["system_events"]
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
                    
            elif topic == "EXEC.TICK":
                self.state["last_ticks"].append(payload)
                if len(self.state["last_ticks"]) > 150:
                    self.state["last_ticks"] = self.state["last_ticks"][-150:]
                    
            elif topic == "EXEC.EVENT":
                import uuid
                if isinstance(payload, dict) and "schema_version" in payload:
                    envelope = payload
                    if "event" in envelope:
                        evt_obj = envelope["event"]
                        if "priority" not in evt_obj:
                            evt_obj["priority"] = get_notification_priority(evt_obj.get("event_type", ""), evt_obj.get("description", ""))
                else:
                    msg = payload.get("message", str(payload)) if isinstance(payload, dict) else str(payload)
                    severity = payload.get("severity", "INFO") if isinstance(payload, dict) else "INFO"
                    source = payload.get("source", "SYSTEM") if isinstance(payload, dict) else "SYSTEM"
                    corr_id = payload.get("correlation_id", "") if isinstance(payload, dict) else ""
                    
                    evt_type = "SYSTEM_EVENT"
                    if source == "FEED":
                        evt_type = "FEED_RESTORED" if "Active" in msg else "FEED_OFFLINE"
                    elif source == "EXECUTION":
                        evt_type = "BUY_EXECUTED" if "BUY" in msg else "SELL_EXECUTED"
                        
                    priority = get_notification_priority(evt_type, msg)
                    
                    envelope = {
                        "schema_version": "1.0",
                        "generated_at": datetime.utcnow().isoformat() + "Z",
                        "engine_version": "1.1.0",
                        "git_commit": "unknown",
                        "event": {
                            "notification_id": str(uuid.uuid4()),
                            "event_type": evt_type,
                            "priority": priority,
                            "severity": severity,
                            "title": f"{source} Event",
                            "description": msg,
                            "timestamp": int(time.time() * 1000),
                            "correlation_id": corr_id,
                            "strategy": "--",
                            "instrument": "--",
                            "premium": None,
                            "pnl": None,
                            "status": "Generated"
                        }
                    }
                
                # Append to history
                self.notification_history.insert(0, envelope)
                if len(self.notification_history) > 500:
                    self.notification_history = self.notification_history[:500]
                
                try:
                    write_envelope_json_atomic(self.notification_history_file, self.notification_history)
                except Exception as e:
                    logger.error(f"Failed to write notification history: {e}")
                    
                # Format legacy event for desktop UI
                legacy_evt = {
                    "timestamp": envelope["event"]["timestamp"],
                    "source": envelope["event"]["event_type"],
                    "message": envelope["event"]["description"],
                    "severity": envelope["event"]["severity"],
                    "correlation_id": envelope["event"].get("correlation_id", "")
                }
                self.state["system_events"].append(legacy_evt)
                if len(self.state["system_events"]) > 200:
                    self.state["system_events"] = self.state["system_events"][-200:]

    def _writer_loop(self):
        """Writes snapshot to disk atomically every 2 seconds."""
        while not self._stop_event.is_set():
            try:
                with self.state_lock:
                    snapshot_copy = json.loads(json.dumps(self.state)) # Deep copy state safely
                write_envelope_json_atomic(self.snapshot_file, snapshot_copy)
            except Exception as e:
                logger.error(f"Error persisting QOT snapshot: {e}")
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
            write_envelope_json_atomic(self.snapshot_file, snapshot_copy)
        except Exception:
            pass

        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=1.0)
        if self.writer_thread and self.writer_thread.is_alive():
            self.writer_thread.join(timeout=1.0)
        logger.info("RuntimeTelemetryAggregator stopped.")
