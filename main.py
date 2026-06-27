import os
import sys
import json
import threading
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, jsonify
from src.core.message_bus import MessageBusSubscriber, EXEC_PORT
from src.utils.logger import get_logger

logger = get_logger("ui_node")

app = Flask(__name__, template_folder='src/web/templates', static_folder='src/web/static')

# Load history if exists
history_data = []
if os.path.exists("trade_history.json"):
    try:
        with open("trade_history.json", 'r') as f:
            history_data = json.load(f)
    except: pass

# UI State Dictionary
state = {
    "status": "running",
    "error_msg": "",
    "telemetry": {},
    "active_trade": None,
    "history": history_data,
    "chart_data": [],
    "errors": []
}

def on_exec_message(topic, payload):
    """Callback for messages coming from the Brain Service via ZeroMQ."""
    global state
    
    if topic == "EXEC.TELEMETRY":
        state["telemetry"].update(payload)
        
    elif topic == "EXEC.ACTIVE_TRADE":
        state["active_trade"] = payload
        
    elif topic == "EXEC.SETUP":
        # New setup pending
        state["active_trade"] = payload  # UI treats pending setups similarly to active for display
        
    elif topic == "EXEC.SIGNAL_RESOLVED":
        signal = payload.get("signal", {})
        if signal.get('signal_category') == 'EXECUTED':
            state["history"].insert(0, signal)
            state["active_trade"] = None
        elif signal.get('signal_category') == 'REJECTED':
            state["active_trade"] = None
            
    elif topic == "EXEC.CHART_SYNC":
        state["chart_data"] = payload

def start_zmq_listener():
    """Background thread that listens to Brain Service events."""
    logger.info("=== STARTING UI ZMQ LISTENER ===")
    sub = MessageBusSubscriber(EXEC_PORT, topics=["EXEC."])
    sub.listen(on_exec_message)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    return jsonify(state)

@app.route('/api/chart_data')
def chart_data():
    try:
        data = state.get("chart_data", [])
        if not data:
            return jsonify([])
            
        df = pd.DataFrame(data)
        
        if 'timestamp' in df.columns:
            # Convert to Unix timestamp for LightweightCharts
            df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
            df['time'] = df['timestamp_dt'].apply(lambda x: int(x.timestamp()))
            
        # Deduplicate
        if 'time' in df.columns:
            df = df.drop_duplicates(subset=['time'], keep='last')
            
        if 'volume' in df.columns:
            df['value'] = df['volume']
        elif 'synth_vol' in df.columns:
            df['value'] = df['synth_vol']
        else:
            df['value'] = 0
            
        df = df.fillna(0)
        
        cols = ['time', 'open', 'high', 'low', 'close', 'value']
        if 'vwap' in df.columns: cols.append('vwap')
        if 'ema_9' in df.columns: cols.append('ema_9')
        if 'vfi' in df.columns: cols.append('vfi')
        if 'vfi_ema' in df.columns: cols.append('vfi_ema')
        
        cols = [c for c in cols if c in df.columns]
        
        json_data = df[cols].to_json(orient='records')
        return app.response_class(json_data, mimetype='application/json')
    except Exception as e:
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    # Start the background subscriber
    t = threading.Thread(target=start_zmq_listener, daemon=True)
    t.start()
    
    logger.info("Starting UI Flask Server on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
