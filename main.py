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
import json
import glob
import threading
import numpy as np
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from src.core.message_bus import MessageBusSubscriber, EXEC_PORT
from src.utils.logger import get_logger
import ipaddress
import time
from src.config.engineering_config import REMOTE_DASHBOARD_ENABLED

logger = get_logger("ui_node")

# Connected Operators Session Cache
connected_operators = {}

def is_private_ip(ip_str):
    if not ip_str:
        return False
    if ip_str in ["localhost", "127.0.0.1", "::1"]:
        return True
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_private or ip.is_loopback
    except ValueError:
        return False

def track_operator(session_id, client_ip, user_agent, quality):
    if not session_id:
        return
    now = time.time()
    
    # Parse Platform & Browser from User-Agent
    platform = "Unknown"
    ua_lower = user_agent.lower() if user_agent else ""
    if "android" in ua_lower:
        platform = "Android"
    elif "iphone" in ua_lower or "ipad" in ua_lower:
        platform = "iOS"
    elif "windows" in ua_lower:
        platform = "Windows"
    elif "macintosh" in ua_lower or "mac os" in ua_lower:
        platform = "macOS"
    elif "linux" in ua_lower:
        platform = "Linux"
        
    browser = "Unknown"
    if "firefox" in ua_lower:
        browser = "Firefox"
    elif "chrome" in ua_lower and "safari" in ua_lower:
        browser = "Chrome"
    elif "safari" in ua_lower and "chrome" not in ua_lower:
        browser = "Safari"
    elif "edge" in ua_lower:
        browser = "Edge"
    elif "opera" in ua_lower or "opr" in ua_lower:
        browser = "Opera"
        
    with state_lock:
        if session_id not in connected_operators:
            connected_operators[session_id] = {
                "session_id": session_id[:8],
                "ip": client_ip,
                "platform": platform,
                "browser": browser,
                "connection_time": datetime.now().strftime('%H:%M:%S'),
                "last_activity": now,
                "connection_quality": quality or "Connected"
            }
        else:
            connected_operators[session_id].update({
                "last_activity": now,
                "connection_quality": quality or "Connected",
                "ip": client_ip
            })
            
    cleanup_inactive_operators()

def cleanup_inactive_operators():
    now = time.time()
    stale_threshold = 30.0
    to_delete = []
    with state_lock:
        for sid, op in connected_operators.items():
            if now - op["last_activity"] > stale_threshold:
                to_delete.append(sid)
        for sid in to_delete:
            del connected_operators[sid]

def get_connected_operators_list():
    cleanup_inactive_operators()
    with state_lock:
        return list(connected_operators.values())

app = Flask(__name__, template_folder='src/web/templates', static_folder='src/web/static')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

@app.before_request
def check_remote_subnet_and_track():
    client_ip = request.remote_addr
    if not is_private_ip(client_ip):
        return "403 Forbidden: Local Subnet LAN Access Only", 403
        
    session_id = request.headers.get("X-Operator-Session-ID")
    quality = request.headers.get("X-Operator-Connection-Quality")
    user_agent = request.headers.get("User-Agent", "")
    if session_id:
        track_operator(session_id, client_ip, user_agent, quality)

# Load history if exists
history_data = []
if os.path.exists("trade_history.json"):
    try:
        with open("trade_history.json", 'r') as f:
            history_data = json.load(f)
    except Exception:
        pass

# Auditor Fix: Module-level telemetry cache
_telemetry_cache = {}

state_lock = threading.Lock()

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

def read_dashboard_snapshot():
    snapshot_path = os.path.join(os.path.dirname(__file__), 'runtime', 'terminal_snapshot.json')
    if os.path.exists(snapshot_path):
        try:
            with open(snapshot_path, 'r', encoding='utf-8') as f:
                envelope = json.load(f)
                return envelope.get("payload", {}) if "payload" in envelope else envelope
        except Exception:
            pass
    return {}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/intelligence_lab')
def intelligence_lab():
    return render_template('intelligence_lab.html')

def read_service_status():
    status_path = os.path.join(os.path.dirname(__file__), 'runtime', 'runtime_status.json')
    if os.path.exists(status_path):
        try:
            with open(status_path, 'r', encoding='utf-8') as f:
                envelope = json.load(f)
                return envelope.get("payload", {}) if "payload" in envelope else envelope
        except Exception as exc:
            logger.warning(f"Could not read service status file: {exc}")
    return {}

def read_startup_validation():
    val_path = os.path.join(os.path.dirname(__file__), 'runtime', 'platform_validation.json')
    if os.path.exists(val_path):
        try:
            with open(val_path, 'r', encoding='utf-8') as f:
                envelope = json.load(f)
                return envelope.get("payload", {}) if "payload" in envelope else envelope
        except Exception:
            pass
    return {}

@app.route('/api/status')
def get_status():
    snapshot = read_dashboard_snapshot()
    status_payload = read_service_status()
    
    # Calculate dataset certification status
    dataset_cert = "Certified"
    audit_dir = os.path.join(os.path.dirname(__file__), 'data', 'audit')
    manifest_file = os.path.join(audit_dir, 'certification_manifest.json')
    if os.path.exists(manifest_file):
        try:
            with open(manifest_file, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
                if manifest and isinstance(manifest, list):
                    latest_audit = manifest[-1]
                    grade = latest_audit.get("grade", "Grade A")
                    if grade in ["Grade F", "FAILED"]:
                        dataset_cert = "FAILED"
                    elif grade == "Grade D":
                        dataset_cert = "WARNING"
        except Exception:
            dataset_cert = "WARNING"
            
    # Calculate dynamic research day
    from datetime import date
    epoch_start = date(2026, 7, 6)
    today_dt = datetime.now().date()
    if today_dt < epoch_start:
        research_day = 1
    else:
        research_day = max(1, (today_dt - epoch_start).days + 1)
        
    from src.utils.provenance import get_provenance_metadata
    try:
        prov = get_provenance_metadata()
        git_commit = prov.get("git_commit", "unknown")
    except Exception:
        git_commit = "unknown"
    
    payload = {
        "status": "running",
        "error_msg": "",
        "telemetry": snapshot.get("telemetry", {}),
        "active_trade": snapshot.get("active_trade"),
        "history": snapshot.get("history", []),
        "chart_data": snapshot.get("chart_data", []),
        "decisions": snapshot.get("decisions", []),
        "last_ticks": snapshot.get("last_ticks", []),
        "system_events": snapshot.get("system_events", []),
        "errors": snapshot.get("errors", []),
        "service_status": status_payload.get('services', {}),
        "system_performance": status_payload.get('system_performance', {}),
        "runtime_validation": status_payload.get('runtime_validation', {}),
        "startup_validation": read_startup_validation(),
        "lifecycle_state": status_payload.get('lifecycle_state', 'OFFLINE'),
        "system_health": status_payload.get('system_health', 'UNKNOWN'),
        "operator_status": {
            "connected_sessions": get_connected_operators_list()
        },
        "service_summary": {
            'engine_pid': status_payload.get('engine_pid'),
            'last_update': status_payload.get('last_update') or snapshot.get("last_update"),
            'schema_version': status_payload.get('schema_version'),
            'platform_version': status_payload.get('platform_version'),
            'generated_at': status_payload.get('generated_at')
        },
        "system_info": {
            "engine_version": "1.1.0",
            "git_commit": git_commit[:7] if git_commit != "unknown" else "unknown",
            "research_epoch": 1,
            "research_day": research_day,
            "broker": "Angel One",
            "dataset_certification": dataset_cert
        }
    }
    return jsonify(payload)

NOTIFICATION_HISTORY_FILE = os.path.join(os.path.dirname(__file__), 'runtime', 'notification_history.json')

def load_notification_history():
    if os.path.exists(NOTIFICATION_HISTORY_FILE):
        try:
            with open(NOTIFICATION_HISTORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_notification_history(history):
    try:
        os.makedirs(os.path.dirname(NOTIFICATION_HISTORY_FILE), exist_ok=True)
        temp_file = NOTIFICATION_HISTORY_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2)
        os.replace(temp_file, NOTIFICATION_HISTORY_FILE)
    except Exception as e:
        logger.error(f"Failed to write notification history: {e}")

@app.route('/api/operator', methods=['GET'])
def operator_dto():
    """Stable, read-only DTO interface for QOT Remote monitoring."""
    snapshot = read_dashboard_snapshot()
    status_payload = read_service_status()
    
    dataset_cert = "Certified"
    audit_dir = os.path.join(os.path.dirname(__file__), 'data', 'audit')
    manifest_file = os.path.join(audit_dir, 'certification_manifest.json')
    if os.path.exists(manifest_file):
        try:
            with open(manifest_file, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
                if manifest and isinstance(manifest, list):
                    latest_audit = manifest[-1]
                    grade = latest_audit.get("grade", "Grade A")
                    if grade in ["Grade F", "FAILED"]:
                        dataset_cert = "FAILED"
                    elif grade == "Grade D":
                        dataset_cert = "WARNING"
        except Exception:
            dataset_cert = "WARNING"
            
    from datetime import date
    epoch_start = date(2026, 7, 6)
    today_dt = datetime.now().date()
    research_day = 1 if today_dt < epoch_start else max(1, (today_dt - epoch_start).days + 1)
        
    from src.utils.provenance import get_provenance_metadata
    try:
        prov = get_provenance_metadata()
        git_commit = prov.get("git_commit", "unknown")
    except Exception:
        git_commit = "unknown"
        
    # Construct clean decoupled DTO
    dto = {
        "active_trade": snapshot.get("active_trade"),
        "notifications": load_notification_history(),
        "feed_health": {
            "heartbeat": "CONNECTED" if (snapshot.get("last_ticks") and (time.time() * 1000 - snapshot["last_ticks"][-1]["timestamp"] < 2000)) else "OFFLINE",
            "tick_rate": len(snapshot.get("last_ticks", [])),
            "clock_drift_ms": int(abs(time.time() * 1000 - (status_payload.get('last_update_ts', time.time()) * 1000))) if status_payload.get('last_update_ts') else 0
        },
        "operator_status": {
            "connected_sessions": get_connected_operators_list()
        },
        "runtime_summary": {
            "lifecycle_state": status_payload.get('lifecycle_state', 'OFFLINE'),
            "system_cpu_percent": status_payload.get('system_performance', {}).get('system_cpu_percent', 0.0),
            "system_ram_percent": status_payload.get('system_performance', {}).get('total_ram_percent', 0.0),
            "platform_ram_mb": sum(s.get('memory_mb', 0.0) for s in status_payload.get('services', {}).values()),
            "services": {name: s.get('state', 'offline') for name, s in status_payload.get('services', {}).items()}
        },
        "system_info": {
            "engine_version": "1.1.0",
            "git_commit": git_commit[:7] if git_commit != "unknown" else "unknown",
            "research_epoch": 1,
            "research_day": research_day,
            "broker": "Angel One",
            "dataset_certification": dataset_cert
        }
    }
    return jsonify(dto)

@app.route('/api/operator/notifications/ack', methods=['POST'])
def acknowledge_notifications():
    """Allows operator browsers to update delivery status of notification IDs."""
    try:
        data = request.get_json()
        if not data or "notifications" not in data:
            return jsonify({"status": "error", "message": "Missing notifications array"}), 400
            
        acks = data["notifications"]
        if not acks:
            return jsonify({"status": "success", "updated": 0})
            
        history = load_notification_history()
        updated_count = 0
        
        # Map notification_id to new status
        ack_map = {item["notification_id"]: item["status"] for item in acks if "notification_id" in item and "status" in item}
        
        for item in history:
            ev = item.get("event", {})
            nid = ev.get("notification_id")
            if nid in ack_map:
                ev["status"] = ack_map[nid]
                updated_count += 1
                
        if updated_count > 0:
            save_notification_history(history)
            
        return jsonify({"status": "success", "updated": updated_count})
    except Exception as e:
        logger.error(f"Error in operator notifications ack: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/time_stop_research')
def get_time_stop_research():
    import polars as pl
    parquet_path = os.path.join("data", "research", "time_stop_analysis.parquet")
    
    response = {
        "ev_curve": [0.0] * 8,
        "best_stop": "N/A",
        "improvement_pct": 0.0,
        "sample_size": 0,
        "confidence": "LOW"
    }
    
    if not os.path.exists(parquet_path):
        return jsonify(response)
        
    try:
        df = pl.read_parquet(parquet_path)
        n = len(df)
        if n == 0:
            return jsonify(response)
            
        marks = ["live_exit_price", "premium_4m", "premium_5m", "premium_6m", "premium_7m", "premium_8m", "premium_9m", "premium_10m"]
        averages = []
        for m in marks:
            avg_val = df[m].mean() if m in df.columns else 0.0
            averages.append(round(float(avg_val), 2) if avg_val is not None else 0.0)
            
        best_idx = 0
        best_val = averages[0]
        for i in range(1, len(averages)):
            if averages[i] > best_val:
                best_val = averages[i]
                best_idx = i
                
        best_stop_minutes = best_idx + 3
        
        base_3m = averages[0]
        improvement = 0.0
        if base_3m > 0.0:
            improvement = ((best_val - base_3m) / base_3m) * 100.0
            
        confidence = "LOW"
        if n >= 20:
            confidence = "HIGH"
        elif n >= 5:
            confidence = "MEDIUM"
            
        response = {
            "ev_curve": averages,
            "best_stop": f"{best_stop_minutes} min",
            "improvement_pct": round(improvement, 2),
            "sample_size": n,
            "confidence": confidence
        }
    except Exception as e:
        logger.error(f"Error calculating EV curve: {e}")
        
    return jsonify(response)

@app.route('/api/audit_status')
def audit_status():
    """Returns the historical certification manifest timeline registry and the latest audit report."""
    audit_dir = os.path.join(os.path.dirname(__file__), 'data', 'audit')
    manifest_file = os.path.join(audit_dir, 'certification_manifest.json')
    
    manifest = []
    if os.path.exists(manifest_file):
        try:
            with open(manifest_file, 'r', encoding='utf-8') as f:
                manifest = json.load(f)
        except Exception:
            pass
            
    latest_report = {}
    try:
        report_files = sorted(glob.glob(os.path.join(audit_dir, 'certification_*.json')))
        if report_files:
            with open(report_files[-1], 'r', encoding='utf-8') as f:
                latest_report = json.load(f)
    except Exception:
        pass
        
    return jsonify({
        "manifest": manifest,
        "latest": latest_report
    })

@app.route('/api/chart_data')
def chart_data():
    try:
        snapshot = read_dashboard_snapshot()
        data = snapshot.get("chart_data", [])
        if not data:
            return jsonify([])
            
        df = pd.DataFrame(data)
        if df.empty:
            return jsonify([])
            
        if 'timestamp' in df.columns:
            df['timestamp_dt'] = pd.to_datetime(df['timestamp'])
            df['time'] = df['timestamp_dt'].apply(lambda x: int(x.timestamp()))
            df = df.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)
            
        closes = df['close'].to_numpy(dtype=float)
        highs = df['high'].to_numpy(dtype=float)
        lows = df['low'].to_numpy(dtype=float)
        volumes = df['volume'].to_numpy(dtype=float)
        
        # Reference EMA 9
        alpha = 2.0 / (9 + 1)
        ref_ema = np.zeros_like(closes)
        if len(closes) > 0:
            ref_ema[0] = closes[0]
            for i in range(1, len(closes)):
                ref_ema[i] = (closes[i] * alpha) + (ref_ema[i-1] * (1.0 - alpha))
                
        # Reference VWAP
        typical_price = (highs + lows + closes) / 3.0
        cum_pv = np.cumsum(typical_price * volumes)
        cum_v = np.cumsum(volumes)
        ref_vwap = np.where(cum_v == 0, closes, cum_pv / cum_v)
        
        # Reference ATR
        tr = np.zeros_like(closes)
        if len(closes) > 0:
            tr[0] = highs[0] - lows[0]
            for i in range(1, len(closes)):
                tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
            ref_atr = np.zeros_like(tr)
            for i in range(len(tr)):
                ref_atr[i] = np.mean(tr[max(0, i-13):i+1])
        else:
            ref_atr = np.array([])
            
        # Reference VFI
        ref_inter = np.zeros_like(typical_price)
        for i in range(1, len(typical_price)):
            ref_inter[i] = np.log(typical_price[i]) - np.log(typical_price[i-1]) if typical_price[i] > 0 and typical_price[i-1] > 0 else 0.0
        ref_vinter = np.zeros_like(ref_inter)
        for i in range(len(ref_inter)):
            ref_vinter[i] = np.std(ref_inter[max(0, i-29):i+1]) if i > 1 else 0.0
        ref_cutoff = 0.2 * ref_vinter * closes
        ref_vave = np.zeros_like(volumes)
        for i in range(len(volumes)):
            ref_vave[i] = np.mean(volumes[max(0, i-129):i+1])
        ref_vave = np.roll(ref_vave, 1)
        if len(ref_vave) > 0: ref_vave[0] = 0.0
        ref_mf = np.zeros_like(typical_price)
        for i in range(1, len(typical_price)):
            ref_mf[i] = typical_price[i] - typical_price[i-1]
        ref_vmax = ref_vave * 2.5
        ref_vc = np.minimum(volumes, ref_vmax)
        ref_vcp = np.zeros_like(volumes)
        ref_vcp[ref_mf > ref_cutoff] = ref_vc[ref_mf > ref_cutoff]
        ref_vcp[ref_mf < -ref_cutoff] = -ref_vc[ref_mf < -ref_cutoff]
        ref_vfi = np.zeros_like(ref_vcp)
        for i in range(len(ref_vcp)):
            vave_val = ref_vave[i]
            ref_vfi[i] = np.sum(ref_vcp[max(0, i-129):i+1]) / vave_val if vave_val > 0 else 0.0
        ref_vfi_ema = np.zeros_like(ref_vfi)
        if len(ref_vfi) > 0:
            ref_vfi_ema[0] = ref_vfi[0]
            for i in range(1, len(ref_vfi)):
                ref_vfi_ema[i] = (ref_vfi[i] / 3.0) + (ref_vfi_ema[i-1] * 2.0 / 3.0)

        df['ema_9_ref'] = ref_ema
        df['vwap_ref'] = ref_vwap
        df['atr_ref'] = ref_atr
        df['vfi_ref'] = ref_vfi_ema
        df['value'] = df['volume']
        
        if 'timestamp_dt' in df.columns:
            df = df.drop(columns=['timestamp_dt'])
            
        json_data = df.to_json(orient='records')
        return app.response_class(json_data, mimetype='application/json')
    except Exception as e:
        logger.error(f"Error in chart_data: {e}")
        return jsonify({"error": str(e)})

@app.route('/api/intelligence/health')
def intel_health():
    """Reads the health_state.json written by health_service.py"""
    try:
        health_path = os.path.join(os.path.dirname(__file__), 'data', 'health_state.json')
        latest = {}
        if os.path.exists(health_path):
            with open(health_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            latest = data.get('latest', {})

        status_payload = read_service_status()
        if status_payload:
            latest['service_status'] = status_payload.get('services', {})
            latest['service_summary'] = {
                'engine_pid': status_payload.get('engine_pid'),
                'started_at': status_payload.get('started_at')
            }

        if not latest:
            return jsonify({"error": "Health data not yet available"})

        return jsonify(latest)
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/api/intelligence/decisions')
def intel_decisions():
    """Returns decision statistics + recent decisions from in-memory buffer and parquet history"""
    try:
        with state_lock:
            # In-memory recent decisions (last 100)
            recent = list(state.get('decisions', []))

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
        with state_lock:
            telemetry = dict(state.get('telemetry', {}))
            chart = list(state.get('chart_data', []))
        
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
        with state_lock:
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
        with state_lock:
            history = list(state.get('history', []))
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

@app.route('/api/logs')
def get_service_logs():
    """Returns the last 200 lines from the requested service log, filtered by severity and search text."""
    service = request.args.get('service', 'brain_service')
    severity = request.args.get('severity', '')
    search_text = request.args.get('search', '').lower()
    
    # Sanitize service name to prevent directory traversal
    service = "".join([c for c in service if c.isalnum() or c in ['_', '-']])
    log_file = os.path.join(os.path.dirname(__file__), 'logs', f"{service}.log")
    
    if not os.path.exists(log_file):
        return jsonify({"lines": [{"text": f"Log file for {service} does not exist.", "level": "WARNING"}], "count": 1})
        
    try:
        lines = []
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            try:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - 150000), os.SEEK_SET) # read ~150KB
            except Exception:
                pass
            
            raw_lines = f.readlines()
            if len(raw_lines) > 1:
                raw_lines = raw_lines[1:]
                
            for line in reversed(raw_lines):
                line_str = line.strip()
                if not line_str:
                    continue
                    
                level = 'INFO'
                if '[ERROR]' in line_str or '[E ' in line_str or 'error' in line_str.lower():
                    level = 'ERROR'
                elif '[WARNING]' in line_str or '[W ' in line_str or 'warning' in line_str.lower():
                    level = 'WARNING'
                elif '[CRITICAL]' in line_str or '[C ' in line_str or 'critical' in line_str.lower():
                    level = 'CRITICAL'
                elif 'SUCCESS' in line_str or 'success' in line_str.lower():
                    level = 'SUCCESS'
                    
                if severity and severity != level:
                    continue
                    
                if search_text and search_text not in line_str.lower():
                    continue
                    
                lines.append({"text": line_str, "level": level})
                if len(lines) >= 200:
                    break
                    
        return jsonify({"lines": list(reversed(lines)), "count": len(lines)})
    except Exception as e:
        return jsonify({"error": str(e), "lines": []})

@app.route('/api/summary')
def get_summaries():
    """Returns aggregated daily, weekly, or monthly summaries."""
    mode = request.args.get('mode', 'daily')
    summary_file = os.path.join(os.path.dirname(__file__), 'data', 'summaries', f"{mode}_summary.json")
    
    if os.path.exists(summary_file):
        try:
            with open(summary_file, 'r', encoding='utf-8') as f:
                return jsonify(json.load(f))
        except Exception as e:
            return jsonify({"error": f"Failed to read summary file: {e}"})
            
    return jsonify([])

@app.route('/api/dataset_health')
def dataset_health():
    """Returns rows, file sizes, last modified times, adaptive expected totals, and status tags."""
    import pyarrow.parquet as pq
    from src.config.data_lifecycle_config import (
        RAW_TICK_RETENTION_DAYS,
        INDICATOR_RETENTION_DAYS,
        DECISION_RETENTION_DAYS
    )
    
    # Fallback/Default expected rows
    expected_ticks = 250000
    expected_features = 50000
    expected_decisions = 250000
    expected_trades = 3
    
    # Try to load adaptive expected totals from daily summaries
    daily_file = os.path.join(os.path.dirname(__file__), 'data', 'summaries', 'daily_summary.json')
    if os.path.exists(daily_file):
        try:
            with open(daily_file, 'r', encoding='utf-8') as f:
                summaries = json.load(f)
                if isinstance(summaries, list) and len(summaries) > 0:
                    last_summary = summaries[-1]
                    dq = last_summary.get("data_quality", {})
                    if dq.get("ticks_collected", 0) > 1000:
                        expected_ticks = dq["ticks_collected"]
                    if dq.get("indicators_written", 0) > 100:
                        expected_features = dq["indicators_written"]
                    if dq.get("decisions_logged", 0) > 10:
                        expected_decisions = dq["decisions_logged"]
                    if dq.get("trades_logged", 0) > 0:
                        expected_trades = dq["trades_logged"]
        except Exception:
            pass
            
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_dt = datetime.now()
    
    def get_status_tag(missing_pct):
        if missing_pct < 10.0: return "HEALTHY"
        if missing_pct < 25.0: return "WARNING"
        return "CRITICAL"

    # 1. Raw Ticks
    tick_path = os.path.join(os.path.dirname(__file__), 'data', 'research', 'ticks', f"{today_str}.parquet")
    tick_stats = {"name": "Raw Tick Dataset", "rows": 0, "size_mb": 0.0, "last_write": "--", "expected": expected_ticks, "missing_pct": 100.0, "status": "CRITICAL", "retention_days": RAW_TICK_RETENTION_DAYS}
    if os.path.exists(tick_path):
        try:
            tick_stats["size_mb"] = round(os.path.getsize(tick_path) / (1024 * 1024), 2)
            tick_stats["last_write"] = datetime.fromtimestamp(os.path.getmtime(tick_path)).strftime('%H:%M:%S')
            tick_stats["rows"] = pq.ParquetFile(tick_path).metadata.num_rows
            tick_stats["missing_pct"] = round(max(0.0, (1 - tick_stats["rows"] / expected_ticks) * 100), 1)
            tick_stats["status"] = get_status_tag(tick_stats["missing_pct"])
        except Exception: pass

    # 2. Features
    feature_dir = os.path.join(os.path.dirname(__file__), 'data', 'institutional_memory', 'indicator_stream', today_dt.strftime('%Y'), today_dt.strftime('%m'), today_dt.strftime('%d'))
    feature_stats = {"name": "Feature Dataset", "rows": 0, "size_mb": 0.0, "last_write": "--", "expected": expected_features, "missing_pct": 100.0, "status": "CRITICAL", "retention_days": INDICATOR_RETENTION_DAYS}
    if os.path.exists(feature_dir):
        try:
            parquet_files = [os.path.join(feature_dir, f) for f in os.listdir(feature_dir) if f.endswith('.parquet')]
            if parquet_files:
                feature_stats["size_mb"] = round(sum(os.path.getsize(p) for p in parquet_files) / (1024 * 1024), 2)
                latest_file = max(parquet_files, key=os.path.getmtime)
                feature_stats["last_write"] = datetime.fromtimestamp(os.path.getmtime(latest_file)).strftime('%H:%M:%S')
                feature_stats["rows"] = sum(pq.ParquetFile(p).metadata.num_rows for p in parquet_files)
                feature_stats["missing_pct"] = round(max(0.0, (1 - feature_stats["rows"] / expected_features) * 100), 1)
                feature_stats["status"] = get_status_tag(feature_stats["missing_pct"])
        except Exception: pass

    # 3. Decisions
    dec_path = os.path.join(os.path.dirname(__file__), 'data', 'decision_history.parquet')
    dec_stats = {"name": "Decision Dataset", "rows": 0, "size_mb": 0.0, "last_write": "--", "expected": expected_decisions, "missing_pct": 100.0, "status": "CRITICAL", "retention_days": DECISION_RETENTION_DAYS}
    if os.path.exists(dec_path):
        try:
            dec_stats["size_mb"] = round(os.path.getsize(dec_path) / (1024 * 1024), 2)
            dec_stats["last_write"] = datetime.fromtimestamp(os.path.getmtime(dec_path)).strftime('%H:%M:%S')
            dec_stats["rows"] = pq.ParquetFile(dec_path).metadata.num_rows
            dec_stats["missing_pct"] = round(max(0.0, (1 - dec_stats["rows"] / expected_decisions) * 100), 1)
            dec_stats["status"] = get_status_tag(dec_stats["missing_pct"])
        except Exception: pass

    # 4. Trades
    trade_path = os.path.join(os.path.dirname(__file__), 'data', 'trades', 'trade_history.json')
    trade_stats = {"name": "Trade Dataset", "rows": 0, "size_mb": 0.0, "last_write": "--", "expected": expected_trades, "missing_pct": 100.0, "status": "CRITICAL", "retention_days": 15}
    if os.path.exists(trade_path):
        try:
            trade_stats["size_mb"] = round(os.path.getsize(trade_path) / 1024, 2)
            trade_stats["last_write"] = datetime.fromtimestamp(os.path.getmtime(trade_path)).strftime('%H:%M:%S')
            with open(trade_path, 'r', encoding='utf-8') as f:
                trades = json.load(f)
                trade_stats["rows"] = len(trades)
                trade_stats["missing_pct"] = round(max(0.0, (1 - trade_stats["rows"] / expected_trades) * 100), 1)
                trade_stats["status"] = get_status_tag(trade_stats["missing_pct"])
        except Exception: pass

    return jsonify({
        "schema_version": "2.0.0",
        "platform_version": "1.0.0",
        "generated_at": datetime.now().isoformat(),
        "datasets": [tick_stats, feature_stats, dec_stats, trade_stats]
    })

if __name__ == '__main__':
    host = '0.0.0.0' if REMOTE_DASHBOARD_ENABLED else '127.0.0.1'
    logger.info(f"Starting UI Flask Server on {host}:5000 (Remote Enabled: {REMOTE_DASHBOARD_ENABLED})...")
    app.run(host=host, port=5000, debug=False, use_reloader=False)
