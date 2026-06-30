# main.py
# QuantOS UI Node — Flask Web Dashboard
# Phase 6.2 — Lean Orchestration
# Governed by: DOC-1.2 Engineering Optimization Roadmap (ASD v1)
#
# Scope: UI-only. Subscribes to Brain Service ZMQ events.
#        Does NOT contain trading logic, ML, or data collection.
#        Trading strategy (VFI + 9 EMA + VWAP) is preserved in brain_service.py
#        Research data collection is handled by research_collector.py
#
# This file is intentionally lean. Do not add ML or execution logic here.

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
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

# Load history if exists
history_data = []
if os.path.exists("trade_history.json"):
    try:
        with open("trade_history.json", 'r') as f:
            history_data = json.load(f)
    except: pass

# Auditor Fix: Module-level telemetry cache
_telemetry_cache = {}

# UI State Dictionary
state = {
    "status": "running",
    "error_msg": "",
    "telemetry": {},
    "active_trade": None,
    "history": history_data,
    "chart_data": [],
    "errors": [],
    "decisions": []
}

def on_exec_message(topic, payload):
    """Callback for messages coming from the Brain Service via ZeroMQ."""
    global state, _telemetry_cache
    
    if topic == "EXEC.TELEMETRY":
        _telemetry_cache.update(payload)
        state["telemetry"] = _telemetry_cache
        
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

    elif topic == "EXEC.DECISION":
        # Keep last 100 decisions in memory
        state["decisions"].insert(0, payload)
        if len(state["decisions"]) > 100:
            state["decisions"] = state["decisions"][:100]

def start_zmq_listener():
    """Background thread that listens to Brain Service events."""
    logger.info("=== STARTING UI ZMQ LISTENER ===")
    sub = MessageBusSubscriber(EXEC_PORT, topics=["EXEC."])
    sub.listen(on_exec_message)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/intelligence_lab')
def intelligence_lab():
    return render_template('intelligence_lab.html')

@app.route('/api/status')
def get_status():
    # Serve from the module-level cache to ensure browser refresh doesn't blank
    state["telemetry"] = _telemetry_cache
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

@app.route('/api/intelligence/health')
def intel_health():
    """Reads the health_state.json written by health_service.py"""
    try:
        health_path = os.path.join(os.path.dirname(__file__), 'data', 'health_state.json')
        if os.path.exists(health_path):
            with open(health_path, 'r') as f:
                data = json.load(f)
            return jsonify(data.get('latest', {}))
        return jsonify({"error": "Health data not yet available"})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/intelligence/decisions')
def intel_decisions():
    """Returns decision statistics + recent decisions from in-memory buffer and parquet history"""
    try:
        # In-memory recent decisions (last 100)
        recent = state.get('decisions', [])
        
        # Also try to get today's totals from parquet
        total = 0
        accepted = 0
        rejected = 0
        reasons = {}
        
        parquet_path = os.path.join(os.path.dirname(__file__), 'data', 'decision_history.parquet')
        if os.path.exists(parquet_path):
            try:
                df = pd.read_parquet(parquet_path)
                today_str = datetime.now().strftime('%Y-%m-%d')
                today_df = df[df['timestamp'].astype(str).str.startswith(today_str)]
                total = len(today_df)
                accepted = int((today_df['status'] == 'ACCEPTED').sum())
                rejected = int((today_df['status'] == 'REJECTED').sum())
                # Top rejection reasons
                rej_df = today_df[today_df['status'] == 'REJECTED']
                if not rej_df.empty:
                    rc = rej_df['human_reason'].value_counts().head(5)
                    reasons = {str(k): int(v) for k, v in rc.items()}
            except Exception as e:
                logger.warning(f"Could not read decision parquet: {e}")
        
        return jsonify({
            'total_today': total,
            'accepted_today': accepted,
            'rejected_today': rejected,
            'rejection_reasons': reasons,
            'recent': recent[:20]
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/intelligence/live_state')
def intel_live_state():
    """Returns the current computed market indicators from the latest telemetry"""
    try:
        telemetry = state.get('telemetry', {})
        chart = state.get('chart_data', [])
        
        # Get latest candle indicators if chart data available
        market_regime = None
        atr = None
        atr_expansion = None
        compression = None
        
        if chart:
            latest = chart[-1] if isinstance(chart, list) else {}
            market_regime = latest.get('market_regime')
            atr = latest.get('atr')
            atr_expansion = latest.get('atr_expansion')
            compression = latest.get('compression')
        
        return jsonify({
            'telemetry': telemetry,
            'market_regime': market_regime,
            'atr': atr,
            'atr_expansion': atr_expansion,
            'compression': compression
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/intelligence/order_flow')
def intel_order_flow():
    """Returns the active setup / trade order flow state from in-memory state"""
    try:
        active = state.get('active_trade')
        return jsonify({
            'active_trade': active,
            'has_active': active is not None
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/intelligence/trades')
def intel_trades():
    """Returns trade history"""
    try:
        history = state.get('history', [])
        # Calculate summary stats
        wins = sum(1 for t in history if t.get('result') == 'WIN')
        losses = sum(1 for t in history if t.get('result') == 'LOSS')
        total_pl = sum(float(t.get('net_pl', 0)) for t in history)
        
        return jsonify({
            'history': history[:50],  # Last 50 trades
            'total_trades': len(history),
            'wins': wins,
            'losses': losses,
            'total_pl': round(total_pl, 2)
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/api/intelligence/logs')
def intel_logs():
    """Reads last 150 lines from today's on-disk log file. Survives Ctrl+R refreshes."""
    try:
        today_str = datetime.now().strftime('%Y-%m-%d')
        log_path = os.path.join(os.path.dirname(__file__), 'logs', today_str, 'app.log')

        lines = []
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
                raw_lines = all_lines[-150:]

            for line in raw_lines:
                line = line.strip()
                if not line:
                    continue
                level = 'INFO'
                if '[ERROR]' in line or '[E ' in line or 'Error' in line:
                    level = 'ERROR'
                elif '[WARNING]' in line or 'WARNING' in line:
                    level = 'WARNING'
                elif '[CRITICAL]' in line or 'CRITICAL' in line:
                    level = 'CRITICAL'
                elif 'SUCCESS' in line or 'complete' in line.lower() or 'started' in line.lower():
                    level = 'SUCCESS'
                lines.append({'text': line, 'level': level})
        else:
            lines.append({'text': f'[{today_str}] No log file found. System may not have started yet.', 'level': 'WARNING'})

        return jsonify({'lines': lines, 'count': len(lines)})
    except Exception as e:
        return jsonify({'error': str(e), 'lines': []})

if __name__ == '__main__':

    # Start the background subscriber
    t = threading.Thread(target=start_zmq_listener, daemon=True)
    t.start()
    
    logger.info("Starting UI Flask Server on port 5000...")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
