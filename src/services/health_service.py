import os
import sys
import time
import json
import threading
import psutil
import pandas as pd
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
import zmq

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from src.core.message_bus import FEED_PORT, EXEC_PORT
from src.utils.logger import get_logger
from src.utils.market_calendar import is_trading_day

logger = get_logger("health_service")

class PassiveHealthMonitor:
    def __init__(self):
        self.running = False
        
        # ZMQ Context
        self.context = zmq.Context()
        self.feed_sub = self.context.socket(zmq.SUB)
        self.feed_sub.connect(f"tcp://127.0.0.1:{FEED_PORT}")
        self.feed_sub.setsockopt_string(zmq.SUBSCRIBE, "TICK")
        
        self.exec_sub = self.context.socket(zmq.SUB)
        self.exec_sub.connect(f"tcp://127.0.0.1:{EXEC_PORT}")
        self.exec_sub.setsockopt_string(zmq.SUBSCRIBE, "SIGNAL")
        
        # State
        self.tick_count = 0
        self.last_tick_time = None
        self.last_signal_time = None
        
        self.history = deque(maxlen=60) # Keep 60 snapshots in JSON
        
        self.data_dir = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../data')))
        self.canonical_dir = self.data_dir / "institutional_memory" / "canonical_observations" / "constituents_state"
        
        self.data_dir.mkdir(exist_ok=True, parents=True)
        
        self.json_path = self.data_dir / "health_state.json"
        self.parquet_path = self.data_dir / "health_history.parquet"
        
    def _zmq_listener(self):
        poller = zmq.Poller()
        poller.register(self.feed_sub, zmq.POLLIN)
        poller.register(self.exec_sub, zmq.POLLIN)
        
        while self.running:
            try:
                socks = dict(poller.poll(1000))
                now = datetime.now().isoformat()
                
                if self.feed_sub in socks:
                    _ = self.feed_sub.recv_string()
                    self.tick_count += 1
                    self.last_tick_time = now
                    
                if self.exec_sub in socks:
                    _ = self.exec_sub.recv_string()
                    self.last_signal_time = now
                    
            except Exception as e:
                pass
                
    def get_process_info(self, script_name):
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'create_time', 'cpu_percent', 'memory_info']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and script_name in ' '.join(cmdline):
                    uptime = time.time() - proc.info['create_time']
                    return {
                        "status": "Healthy",
                        "pid": proc.info['pid'],
                        "cpu_percent": proc.cpu_percent(interval=0.1),
                        "memory_mb": round(proc.info['memory_info'].rss / (1024 * 1024), 2),
                        "uptime_seconds": round(uptime, 1)
                    }
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return {"status": "Critical", "pid": None, "cpu_percent": 0.0, "memory_mb": 0.0, "uptime_seconds": 0.0}

    def get_canonical_stats(self):
        if not self.canonical_dir.exists():
            return {"status": "Warning", "last_flush": None, "total_files": 0, "total_size_mb": 0}
            
        parquet_files = list(self.canonical_dir.glob("**/*.parquet"))
        if not parquet_files:
            return {"status": "Warning", "last_flush": None, "total_files": 0, "total_size_mb": 0}
            
        latest_file = max(parquet_files, key=lambda f: f.stat().st_mtime)
        mtime = datetime.fromtimestamp(latest_file.stat().st_mtime)
        
        total_size = sum(f.stat().st_size for f in parquet_files) / (1024 * 1024)
        
        now = datetime.now()
        status = "Healthy"
        if is_trading_day() and (now - mtime).total_seconds() > 300: # 5 mins
            status = "Warning"
            
        return {
            "status": status,
            "last_flush": mtime.isoformat(),
            "total_files": len(parquet_files),
            "total_size_mb": round(total_size, 2)
        }

    def get_system_stats(self):
        disk = psutil.disk_usage(str(self.data_dir.absolute()))
        return {
            "cpu_usage_percent": psutil.cpu_percent(interval=0.1),
            "ram_usage_percent": psutil.virtual_memory().percent,
            "disk_usage_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 2)
        }

    def compute_health_score(self, feed_info, brain_info, research_info, canonical_info, tick_rate):
        score = 100
        
        if feed_info['status'] == 'Critical': score -= 25
        if brain_info['status'] == 'Critical': score -= 25
        if research_info['status'] == 'Critical': score -= 20
        
        if is_trading_day():
            if tick_rate == 0 and feed_info['status'] != 'Critical':
                score -= 20
            if canonical_info['status'] == 'Warning':
                score -= 10
                
        return max(0, score)

    def generate_snapshot(self):
        current_ticks = self.tick_count
        self.tick_count = 0
        
        feed_info = self.get_process_info("feed_service.py")
        brain_info = self.get_process_info("brain_service.py")
        research_info = self.get_process_info("research_service.py")
        
        canonical_info = self.get_canonical_stats()
        system_info = self.get_system_stats()
        
        tick_rate = round(current_ticks / 60.0, 2)
        
        score = self.compute_health_score(feed_info, brain_info, research_info, canonical_info, tick_rate)
        
        snapshot = {
            "timestamp": datetime.now().isoformat(),
            "health_score": score,
            "is_trading_day": is_trading_day(),
            "feed_service": {
                **feed_info,
                "last_tick": self.last_tick_time,
                "ticks_per_sec_last_minute": tick_rate
            },
            "brain_service": {
                **brain_info,
                "last_signal": self.last_signal_time
            },
            "research_collector": research_info,
            "canonical_storage": canonical_info,
            "system": system_info
        }
        
        return snapshot

    def start(self):
        self.running = True
        threading.Thread(target=self._zmq_listener, daemon=True).start()
        logger.info("Passive Health Monitor started. ZMQ Sniffing active.")
        
        while self.running:
            time.sleep(60) # Poll every minute
            try:
                snapshot = self.generate_snapshot()
                self.history.append(snapshot)
                
                # Write JSON
                with open(self.json_path, 'w') as f:
                    json.dump({
                        "latest": snapshot,
                        "history": list(self.history)
                    }, f, indent=2)
                    
                # Write Parquet
                df = pd.json_normalize([snapshot])
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                
                if self.parquet_path.exists():
                    existing_df = pd.read_parquet(self.parquet_path)
                    df = pd.concat([existing_df, df], ignore_index=True)
                
                df.to_parquet(self.parquet_path, engine='pyarrow')
                
                logger.info(f"Health Snapshot Saved | Score: {snapshot['health_score']} | Ticks/s: {snapshot['feed_service']['ticks_per_sec_last_minute']}")
                
            except Exception as e:
                logger.error(f"Error generating health snapshot: {e}")

if __name__ == "__main__":
    monitor = PassiveHealthMonitor()
    try:
        monitor.start()
    except KeyboardInterrupt:
        logger.info("Shutting down Passive Health Monitor")
        monitor.running = False
