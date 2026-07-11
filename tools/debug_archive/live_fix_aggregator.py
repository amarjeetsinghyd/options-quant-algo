"""
live_fix_aggregator.py
----------------------
Injects a fresh telemetry aggregator thread into the running start_all.py process
by writing directly to the terminal_snapshot.json from a ZMQ subscription.
This is an out-of-process fix that runs in a SEPARATE process and bridges the gap
until the engine is next restarted (which will pick up the code fix automatically).

Run with: venv\Scripts\python.exe live_fix_aggregator.py
"""
import sys
import os
sys.path.insert(0, r"C:\Quant")
os.chdir(r"C:\Quant")

import json
import time
import threading
from datetime import datetime

from src.core.message_bus import MessageBusSubscriber, EXEC_PORT
from src.utils.file_utils import write_envelope_json_atomic
from src.utils.logger import get_logger

logger = get_logger("live_fix_aggregator")

SNAPSHOT_FILE = r"C:\Quant\runtime\terminal_snapshot.json"

# Load existing snapshot state so we don't lose history/decisions
state = {
    "status": "running",
    "error_msg": "",
    "telemetry": {},
    "active_trade": None,
    "history": [],
    "decisions": [],
    "last_ticks": [],
    "system_events": [],
    "last_update": None
}

if os.path.exists(SNAPSHOT_FILE):
    try:
        with open(SNAPSHOT_FILE, 'r', encoding='utf-8') as f:
            envelope = json.load(f)
            existing = envelope.get("payload", {}) if "payload" in envelope else envelope
            # Preserve existing history, decisions, system_events
            for key in ["history", "decisions", "last_ticks", "system_events"]:
                if existing.get(key):
                    state[key] = existing[key]
        logger.info(f"Loaded existing snapshot state (history: {len(state['history'])}, decisions: {len(state['decisions'])})")
    except Exception as e:
        logger.warning(f"Could not load existing snapshot: {e}")

state_lock = threading.Lock()
stop_event = threading.Event()

def on_message(topic, payload):
    with state_lock:
        state["last_update"] = datetime.now().isoformat()
        if topic == "EXEC.TELEMETRY":
            if isinstance(state["telemetry"], dict) and isinstance(payload, dict):
                state["telemetry"].update(payload)
            else:
                state["telemetry"] = payload
        elif topic == "EXEC.ACTIVE_TRADE":
            state["active_trade"] = payload
        elif topic == "EXEC.SETUP":
            state["active_trade"] = payload
        elif topic == "EXEC.DECISION":
            state["decisions"].insert(0, payload)
            if len(state["decisions"]) > 100:
                state["decisions"] = state["decisions"][:100]
        elif topic == "EXEC.TICK":
            state["last_ticks"].append(payload)
            if len(state["last_ticks"]) > 150:
                state["last_ticks"] = state["last_ticks"][-150:]

def writer_loop():
    while not stop_event.is_set():
        try:
            with state_lock:
                snapshot_copy = json.loads(json.dumps(state))
            write_envelope_json_atomic(SNAPSHOT_FILE, snapshot_copy)
        except Exception as e:
            logger.error(f"Error writing snapshot: {e}")
        time.sleep(2)

def zmq_loop():
    while not stop_event.is_set():
        try:
            subscriber = MessageBusSubscriber(EXEC_PORT, topics=["EXEC."])
            logger.info("Connected to EXEC ZMQ bus, listening for telemetry...")
            subscriber.listen(on_message)
        except Exception as e:
            logger.error(f"ZMQ error: {e}. Reconnecting in 3s...")
            time.sleep(3)

# Start threads
writer_thread = threading.Thread(target=writer_loop, name="SnapshotWriter", daemon=True)
zmq_thread = threading.Thread(target=zmq_loop, name="ZmqListener", daemon=True)
writer_thread.start()
zmq_thread.start()

logger.info("=== Live Fix Aggregator Running ===")
logger.info(f"Writing to: {SNAPSHOT_FILE}")
logger.info("Press Ctrl+C to stop.")

try:
    while True:
        time.sleep(10)
        with state_lock:
            ltp = state["telemetry"].get("ltp", "N/A")
            last_upd = state["last_update"] or "N/A"
        logger.info(f"[OK] snapshot active | LTP={ltp} | last_update={last_upd}")
except KeyboardInterrupt:
    logger.info("Stopping live fix aggregator...")
    stop_event.set()