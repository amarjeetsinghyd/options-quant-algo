import os
import json
import time
from datetime import datetime
import pyarrow.parquet as pq
from src.utils.logger import get_logger
from src.utils.file_utils import write_json_atomic

logger = get_logger("summary_generator")

DAILY_SUMMARY_PATH = os.path.join("data", "summaries", "daily_summary.json")

def generate_daily_summary(market_date_str: str = None) -> dict:
    """
    Aggregates and writes an EOD session summary for market_date_str.
    Is idempotent: overwrites existing date record.
    """
    if market_date_str is None:
        market_date_str = datetime.now().strftime('%Y-%m-%d')
        
    logger.info(f"Generating EOD daily summary for date: {market_date_str}...")
    
    # 1. Load existing summaries
    summaries = []
    if os.path.exists(DAILY_SUMMARY_PATH):
        try:
            with open(DAILY_SUMMARY_PATH, 'r', encoding='utf-8') as f:
                summaries = json.load(f)
                if not isinstance(summaries, list):
                    summaries = []
        except Exception as e:
            logger.warning(f"Could not read existing daily summaries: {e}")
            
    # 2. Gather snapshot & service metrics
    snapshot_path = os.path.join("runtime", "terminal_snapshot.json")
    snapshot = {}
    if os.path.exists(snapshot_path):
        try:
            with open(snapshot_path, 'r', encoding='utf-8') as f:
                envelope = json.load(f)
                snapshot = envelope.get("payload") if "payload" in envelope else envelope
        except Exception:
            pass
            
    status_path = os.path.join("runtime", "runtime_status.json")
    status = {}
    if os.path.exists(status_path):
        try:
            with open(status_path, 'r', encoding='utf-8') as f:
                envelope = json.load(f)
                status = envelope.get("payload") if "payload" in envelope else envelope
        except Exception:
            pass

    perf = status.get("system_performance", {})
    telemetry = snapshot.get("telemetry", {})
    strategy_stats = telemetry.get("strategy_stats", {})

    # 3. Read Trade History (data/trades/trade_history.json)
    trades_path = os.path.join("data", "trades", "trade_history.json")
    todays_trades = []
    if os.path.exists(trades_path):
        try:
            with open(trades_path, 'r', encoding='utf-8') as f:
                all_trades = json.load(f)
                
                today_dt = datetime.strptime(market_date_str, '%Y-%m-%d')
                day_num = int(today_dt.strftime('%d'))
                month_abbr = today_dt.strftime('%b')
                date_match = f"{day_num:02d} {month_abbr}"
                
                for t in all_trades:
                    t_date = t.get("date", "")
                    if date_match in t_date:
                        todays_trades.append(t)
        except Exception as e:
            logger.error(f"Error reading trade history: {e}")

    # Calculate trade metrics
    total_trades = len(todays_trades)
    wins = sum(1 for t in todays_trades if t.get("result") == "WIN")
    losses = sum(1 for t in todays_trades if t.get("result") == "LOSS")
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    net_pl = sum(t.get("net_pl", 0.0) for t in todays_trades)
    avg_expansion = sum(t.get("opt_pct", 0.0) for t in todays_trades) / total_trades if total_trades > 0 else 0.0
    
    # Calculate duration average
    durations = []
    for t in todays_trades:
        dur_str = t.get("duration", "0s")
        parts = dur_str.split()
        secs = 0
        for p in parts:
            if p.endswith('m'):
                try: secs += int(p[:-1]) * 60
                except: pass
            elif p.endswith('s'):
                try: secs += int(p[:-1])
                except: pass
        durations.append(secs)
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    # 4. Gather Parquet Row counts (Data Quality Section)
    ticks_path = os.path.join("data", "research", "ticks", f"{market_date_str}.parquet")
    ticks_collected = 0
    if os.path.exists(ticks_path):
        try: ticks_collected = pq.ParquetFile(ticks_path).metadata.num_rows
        except Exception: pass
        
    features_written = 0
    today_dt = datetime.strptime(market_date_str, '%Y-%m-%d')
    feature_dir = os.path.join("data", "institutional_memory", "indicator_stream", today_dt.strftime('%Y'), today_dt.strftime('%m'), today_dt.strftime('%d'))
    if os.path.exists(feature_dir):
        try:
            parquet_files = [os.path.join(feature_dir, f) for f in os.listdir(feature_dir) if f.endswith('.parquet')]
            features_written = sum(pq.ParquetFile(p).metadata.num_rows for p in parquet_files)
        except Exception: pass
        
    decisions_logged = 0
    dec_path = os.path.join("data", "decision_history.parquet")
    if os.path.exists(dec_path):
        try:
            decisions_logged = sum(strategy_stats.get(s, {}).get("observed", 0) for s in ["Strategy 1", "Strategy 2", "Strategy 3"])
            if decisions_logged == 0:
                decisions_logged = pq.ParquetFile(dec_path).metadata.num_rows
        except Exception: pass

    # Log write errors scan
    write_errors = 0
    for service_log in ["start_all", "brain_service", "feed_service", "research_collector", "decision_journal"]:
        log_file = os.path.join("logs", f"{service_log}.log")
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as lf:
                    content = lf.read()
                    write_errors += content.count("[ERROR]") + content.count("[CRITICAL]")
            except Exception: pass

    # Last successful backup/flush times
    last_flush = datetime.now().strftime('%H:%M:%S') if ticks_collected > 0 else "--"
    last_backup = "--"
    backup_status_file = os.path.join("runtime", "backup_status.json")
    if os.path.exists(backup_status_file):
        try:
            with open(backup_status_file, 'r') as f:
                last_backup = json.load(f).get("last_successful_backup", "--")
        except Exception: pass

    # 5. Compile the Daily Summary Entry
    summary_entry = {
        "summary_metadata": {
            "summary_version": "1.0",
            "generated_at": datetime.now().isoformat(),
            "market_date": market_date_str,
            "engine_version": "1.0.0",
            "git_commit": "v1.0.0-research-baseline",
            "strategy_hash": "a98f12c8b",
            "schema_version": "2.0.0"
        },
        "data_quality": {
            "ticks_collected": ticks_collected,
            "indicators_written": features_written,
            "decisions_logged": decisions_logged,
            "trades_logged": total_trades,
            "missing_files": 0 if ticks_collected > 0 else 1,
            "write_errors": write_errors,
            "last_successful_flush": last_flush,
            "last_successful_backup": last_backup
        },
        "system_performance": {
            "cpu_peak": perf.get("peak_cpu_percent", 0.0),
            "ram_peak": perf.get("peak_ram_percent", 0.0),
            "ticks_per_second_peak": telemetry.get("tick_rate", 0.0),
            "decision_latency_avg_ms": telemetry.get("decision_latency_ms", 0.0)
        },
        "strategy_performance": {},
        "trade_metrics": {
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "net_pl": net_pl,
            "avg_hold_time_seconds": avg_duration,
            "avg_premium_expansion_pct": avg_expansion
        }
    }

    # Populate strategy stats
    for sName in ["Strategy 1", "Strategy 2", "Strategy 3"]:
        s_data = strategy_stats.get(sName, {})
        s_trades = [t for t in todays_trades if t.get("strategy") == sName]
        s_total = len(s_trades)
        s_wins = sum(1 for t in s_trades if t.get("result") == "WIN")
        s_win_rate = (s_wins / s_total * 100) if s_total > 0 else 0.0
        s_opt_pct = sum(t.get("opt_pct", 0.0) for t in s_trades) / s_total if s_total > 0 else 0.0
        
        summary_entry["strategy_performance"][sName] = {
            "observed": s_data.get("observed", 0),
            "candidate": s_data.get("candidate", 0),
            "filtered": s_data.get("filtered", 0),
            "rejected": s_data.get("rejected", 0),
            "expired": s_data.get("expired", 0),
            "executed": s_data.get("executed", s_total),
            "win_rate": s_win_rate,
            "avg_premium_expansion": s_opt_pct
        }

    # 6. Idempotently update
    summaries = [s for s in summaries if s.get("summary_metadata", {}).get("market_date") != market_date_str]
    summaries.append(summary_entry)
    
    # 7. Write atomic
    write_json_atomic(DAILY_SUMMARY_PATH, summaries)
    logger.info("EOD daily summary generated successfully!")
    return summary_entry
