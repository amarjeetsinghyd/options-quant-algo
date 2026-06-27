import time
import threading
import collections
import os
from abc import ABC, abstractmethod
from src.config.engineering_config import PROFILING_ENABLED, SYSTEM_METRICS_INTERVAL

# Global toggle to enable/disable profiling hooks.
# When False, decorators return the original function directly, avoiding wrapper overhead.

class PerformanceCollector(ABC):
    """
    Abstract base class defining interface for performance data collection.
    Allows easy future plug-in migrations to Prometheus, Grafana PushGateways, etc.
    """
    @abstractmethod
    def record_tick(self, latency_ms, duration_ms, queue_len, dropped=False):
        pass

    @abstractmethod
    def record_db(self, op_type, duration_ms, is_lock=False, busy_dur=0.0):
        pass

    @abstractmethod
    def record_worker(self, name, duration_ms, idle_time_ms):
        pass

    @abstractmethod
    def record_websocket(self, reconnects, packet_delay_ms):
        pass

    @abstractmethod
    def record_api(self, route, duration_ms):
        pass


class StatsTracker:
    """
    Thread-safe sliding window metrics accumulator.
    Computes Average, Median, P95, P99, and Max from a sliding buffer of size 1000.
    """
    def __init__(self, maxlen=1000):
        self.buffer = collections.deque(maxlen=maxlen)

    def add(self, value):
        self.buffer.append(value)

    def get_stats(self):
        if not self.buffer:
            return {"avg": 0.0, "median": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0, "count": 0}
        
        arr = sorted(list(self.buffer))
        n = len(arr)
        
        def pct(p):
            idx = int(p / 100.0 * (n - 1))
            return float(arr[idx])

        return {
            "avg": float(sum(arr) / n),
            "median": pct(50),
            "p95": pct(95),
            "p99": pct(99),
            "max": float(arr[-1]),
            "count": n
        }


class MemoryCollector(PerformanceCollector):
    """
    Local in-memory concrete metrics collector implementation.
    Standardized Telemetry Version v1.0.
    """
    def __init__(self):
        self.telemetry_version = "v1.0"
        
        # Stats Trackers (Sliding Window buffers)
        self.tick_latency = StatsTracker()
        self.tick_duration = StatsTracker()
        self.db_read_latency = StatsTracker()
        self.db_write_latency = StatsTracker()
        self.db_transaction_duration = StatsTracker()
        self.db_commit_duration = StatsTracker()
        self.worker_execution = StatsTracker()
        self.worker_idle = StatsTracker()
        self.ws_packet_delay = StatsTracker()
        self.api_duration = StatsTracker()

        # Cumulative Counters
        self.active_db_connections = 0
        self.db_lock_count = 0
        self.db_busy_duration = 0.0
        self.ws_reconnect_count = 0
        self.ws_uptime_start = time.time()
        self.ticks_count = 0
        self.dropped_ticks = 0
        self.ticks_queue_length = 0
        self.active_thread_count = 0

        # System Scraped Metrics
        self.system_metrics = {
            "total_cpu": 0.0,
            "cpu_per_core": [],
            "ram_percent": 0.0,
            "process_memory_mb": 0.0,
            "open_file_handles": 0,
            "active_db_connections": 0
        }
        
        self.lock = threading.Lock()

    def record_tick(self, latency_ms, duration_ms, queue_len, dropped=False):
        with self.lock:
            self.ticks_count += 1
            if dropped:
                self.dropped_ticks += 1
            self.ticks_queue_length = queue_len
            if latency_ms >= 0:
                self.tick_latency.add(latency_ms)
            if duration_ms >= 0:
                self.tick_duration.add(duration_ms)

    def record_db(self, op_type, duration_ms, is_lock=False, busy_dur=0.0):
        with self.lock:
            if op_type == "read":
                self.db_read_latency.add(duration_ms)
            elif op_type == "write":
                self.db_write_latency.add(duration_ms)
            elif op_type == "transaction":
                self.db_transaction_duration.add(duration_ms)
            elif op_type == "commit":
                self.db_commit_duration.add(duration_ms)

            if is_lock:
                self.db_lock_count += 1
            if busy_dur > 0:
                self.db_busy_duration += busy_dur

    def record_worker(self, name, duration_ms, idle_time_ms):
        with self.lock:
            if duration_ms >= 0:
                self.worker_execution.add(duration_ms)
            if idle_time_ms >= 0:
                self.worker_idle.add(idle_time_ms)

    def record_websocket(self, reconnects, packet_delay_ms):
        with self.lock:
            self.ws_reconnect_count += reconnects
            if packet_delay_ms >= 0:
                self.ws_packet_delay.add(packet_delay_ms)

    def record_api(self, route, duration_ms):
        with self.lock:
            if duration_ms >= 0:
                self.api_duration.add(duration_ms)

    def update_system_metrics(self, metrics):
        with self.lock:
            self.system_metrics.update(metrics)
            # Synchronize database connection metrics
            self.system_metrics["active_db_connections"] = self.active_db_connections

    def get_metrics_json(self):
        with self.lock:
            self.active_thread_count = threading.active_count()
            return {
                "telemetry_version": self.telemetry_version,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "system": self.system_metrics,
                "tick_pipeline": {
                    "count": self.ticks_count,
                    "dropped": self.dropped_ticks,
                    "queue_length": self.ticks_queue_length,
                    "latency": self.tick_latency.get_stats(),
                    "duration": self.tick_duration.get_stats()
                },
                "database": {
                    "lock_count": self.db_lock_count,
                    "busy_duration": self.db_busy_duration,
                    "active_connections": self.active_db_connections,
                    "read_latency": self.db_read_latency.get_stats(),
                    "write_latency": self.db_write_latency.get_stats(),
                    "transaction_duration": self.db_transaction_duration.get_stats(),
                    "commit_duration": self.db_commit_duration.get_stats()
                },
                "workers": {
                    "active_threads": self.active_thread_count,
                    "execution_time": self.worker_execution.get_stats(),
                    "idle_time": self.worker_idle.get_stats()
                },
                "websocket": {
                    "reconnect_count": self.ws_reconnect_count,
                    "uptime_seconds": int(time.time() - self.ws_uptime_start),
                    "packet_delay": self.ws_packet_delay.get_stats()
                },
                "api": {
                    "duration": self.api_duration.get_stats()
                }
            }


# Singleton Memory Collector Instance
collector = MemoryCollector()


# --- Profiling Decorators (Zero Runtime Overhead when PROFILING_ENABLED = False) ---

def profile_tick(func):
    if not PROFILING_ENABLED:
        return func
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        res = func(*args, **kwargs)
        duration_ms = (time.perf_counter() - start) * 1000
        collector.record_tick(-1, duration_ms, 0)
        return res
    return wrapper


def profile_db(op_type="read"):
    def decorator(func):
        if not PROFILING_ENABLED:
            return func
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            res = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            collector.record_db(op_type, duration_ms)
            return res
        return wrapper
    return decorator


def profile_worker(name="worker"):
    def decorator(func):
        if not PROFILING_ENABLED:
            return func
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            res = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            collector.record_worker(name, duration_ms, 0)
            return res
        return wrapper
    return decorator


def profile_dashboard(route):
    def decorator(func):
        if not PROFILING_ENABLED:
            return func
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            res = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start) * 1000
            collector.record_api(route, duration_ms)
            return res
        return wrapper
    return decorator


# --- System Scraper Background Thread ---

def _system_scraper_run(interval=SYSTEM_METRICS_INTERVAL):
    import psutil
    pid = os.getpid()
    proc = psutil.Process(pid)
    
    # Initialize CPU checks
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)
    
    while True:
        try:
            total_cpu = psutil.cpu_percent(interval=None)
            cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
            ram = psutil.virtual_memory()
            proc_mem = proc.memory_info().rss / (1024 * 1024) # RSS in MB
            
            try:
                open_handles = len(proc.open_files())
            except Exception:
                open_handles = 0
                
            collector.update_system_metrics({
                "total_cpu": total_cpu,
                "cpu_per_core": cpu_per_core,
                "ram_percent": ram.percent,
                "process_memory_mb": proc_mem,
                "open_file_handles": open_handles
            })
        except Exception:
            pass
        time.sleep(interval)


def start_system_scraper(interval=SYSTEM_METRICS_INTERVAL):
    """Starts the background system performance scraping loop thread."""
    t = threading.Thread(target=_system_scraper_run, args=(interval,), daemon=True, name="SystemMetricsScraper")
    t.start()


# --- Database Hook wrappers for SQLite ---
import sqlite3
from src.config.engineering_config import PROFILING_ENABLED, SYSTEM_METRICS_INTERVAL

class InstrumentedCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        op_type = "write" if any(x in sql.lower() for x in ["insert", "update", "delete", "replace", "drop", "create", "alter"]) else "read"
        start = time.perf_counter()
        try:
            return super().execute(sql, parameters)
        finally:
            dur = (time.perf_counter() - start) * 1000
            collector.record_db(op_type, dur)
            # Log slow queries (>100ms)
            if dur > 100.0:
                # Log slow query message to warning if standard logger is importable
                try:
                    from src.utils.logger import get_logger
                    get_logger("db").warning(f"SLOW QUERY ({dur:.2f}ms): {sql[:100]}...")
                except Exception:
                    pass

    def executemany(self, sql, seq_of_parameters):
        op_type = "write" if any(x in sql.lower() for x in ["insert", "update", "delete", "replace", "drop", "create", "alter"]) else "read"
        start = time.perf_counter()
        try:
            return super().executemany(sql, seq_of_parameters)
        finally:
            dur = (time.perf_counter() - start) * 1000
            collector.record_db(op_type, dur)


class InstrumentedConnection(sqlite3.Connection):
    def cursor(self, cursorClass=InstrumentedCursor):
        return super().cursor(cursorClass)

    def commit(self):
        start = time.perf_counter()
        try:
            super().commit()
        finally:
            dur = (time.perf_counter() - start) * 1000
            collector.record_db("commit", dur)


def get_db_connection(db_path, **kwargs):
    """
    Exposes an instrumented SQLite connection factory that automatically tracks
    read/write latency, slow queries, and active connection handles.
    """
    with collector.lock:
        collector.active_db_connections += 1
    
    # Configure custom factory
    kwargs.setdefault("factory", InstrumentedConnection)
    conn = sqlite3.connect(db_path, **kwargs)
    
    # Wrap close to decrement connection counter
    original_close = conn.close
    def close_wrapper():
        try:
            original_close()
        finally:
            with collector.lock:
                collector.active_db_connections = max(0, collector.active_db_connections - 1)
    
    conn.close = close_wrapper
    return conn

