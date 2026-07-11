#!/usr/bin/env python3
"""
start_all.py

Orchestration script for the options-quant-algo system.
Launches and supervises microservices in a data-driven, state-transition-aware manner.
Allows background execution without flashing command/PowerShell windows on Windows.
"""

import json
import os
import sys
import signal
import time
import threading
import socket
import psutil
import subprocess
import datetime as datetime_mod
from datetime import timedelta, time as dtime
from collections import deque
from typing import Dict, List, Optional, Any
from abc import ABC, abstractmethod

# Create a lightweight wrapper so tests can monkey‑patch ``now`` safely.
class _DateTimeWrapper:
    @staticmethod
    def now():
        return datetime_mod.datetime.now()

    @staticmethod
    def combine(date, time):
        return datetime_mod.datetime.combine(date, time)

# Expose the wrapper under the name ``datetime`` for backward compatibility.
datetime = _DateTimeWrapper

from src.utils.file_utils import write_envelope_json_atomic
# RuntimeTelemetryAggregator is now a supervised external service (live_fix_aggregator.py)
# from src.core.telemetry_aggregator import RuntimeTelemetryAggregator

from src.config.engineering_config import (
    DATA_DIR, 
    LOGS_DIR,
    SUPERVISOR_POLLING_INTERVAL_SECONDS,
    SUPERVISOR_RESTART_DELAY_SECONDS,
    SUPERVISOR_MAX_RESTARTS,
    SUPERVISOR_MAX_RESTART_WINDOW_SECONDS,
    ENABLE_SHADOW_SERVICE
)
from src.core.process_launcher import ProcessLauncher
from src.core.shutdown_manager import ShutdownManager
from src.utils.logger import get_logger
from src.utils.market_calendar import is_trading_day

logger = get_logger("start_all")

# Import the generic broker validation runner – this keeps start_all broker‑neutral.
from src.broker.validation.runner import run_broker_validation

SERVICE_STATUS_FILE = os.path.join(os.path.dirname(__file__), "runtime", "runtime_status.json")
PID_FILE = os.path.join(os.path.dirname(__file__), "runtime", "quant_engine.pid")

# ── Service definitions ───────────────────────────────────────────────────
SERVICES = [
    {
        "name": "feed_service",
        "command": [sys.executable, "src/services/feed_service.py"],
        "role": "TRADING",
        "enabled": True,
        "restart_policy": "on-failure",
        "critical": True,
        "startup_priority": 10,
        "capabilities": ["live-feed", "tick-ingestion"],
    },
    {
        "name": "brain_service",
        "command": [sys.executable, "src/services/brain_service.py"],
        "role": "TRADING",
        "enabled": True,
        "restart_policy": "on-failure",
        "critical": True,
        "startup_priority": 9,
        "capabilities": ["order-routing", "signal-generation"],
    },
    {
        "name": "research_collector",
        "command": [sys.executable, "src/services/research_service.py"],
        "role": "SYSTEM",
        "enabled": True,
        "restart_policy": "always",
        "critical": False,
        "startup_priority": 8,
        "capabilities": ["data-collection"],
    },
    {
        "name": "web_dashboard",
        "command": [sys.executable, "main.py"],
        "role": "UI",
        "enabled": True,
        "restart_policy": "always",
        "critical": False,
        "startup_priority": 7,
        "capabilities": ["web-ui"],
    },
    {
        "name": "maintenance_service",
        "command": [sys.executable, "src/services/maintenance_service.py"],
        "role": "SCHEDULER",
        "enabled": True,
        "restart_policy": "always",
        "critical": False,
        "startup_priority": 5,
        "capabilities": ["eod-tasks"],
    },
    {
        "name": "gap_fill_service",
        "command": [sys.executable, "src/services/gap_fill_service.py"],
        "role": "SCHEDULER",
        "enabled": True,
        "restart_policy": "on-failure",
        "critical": False,
        "startup_priority": 4,
        "capabilities": ["data-validation"],
    },
    {
        "name": "health_monitor",
        "command": [sys.executable, "src/services/health_service.py"],
        "role": "SYSTEM",
        "enabled": True,
        "restart_policy": "always",
        "critical": False,
        "startup_priority": 6,
        "capabilities": ["health-check"],
    },
    {
        "name": "decision_journal",
        "command": [sys.executable, "src/services/decision_journal.py"],
        "role": "SYSTEM",
        "enabled": True,
        "restart_policy": "always",
        "critical": False,
        "startup_priority": 3,
        "capabilities": ["decision-logging"],
    },
    {
        "name": "shadow_service",
        "command": [sys.executable, "src/services/shadow_service.py"],
        "role": "SYSTEM",
        "enabled": ENABLE_SHADOW_SERVICE,
        "restart_policy": "on-failure",
        "critical": False,
        "startup_priority": 2,
        "capabilities": ["shadow-trading"],
    },
    {
        "name": "cloud_backup",
        "command": [sys.executable, "src/services/cloud_backup.py"],
        "role": "SCHEDULER",
        "enabled": True,
        "restart_policy": "on-failure",
        "critical": False,
        "startup_priority": 1,
        "capabilities": ["data-archiving"],
    },
    {
        "name": "telemetry_aggregator",
        "command": [sys.executable, "live_fix_aggregator.py"],
        "role": "SYSTEM",
        "enabled": True,
        "restart_policy": "always",
        "critical": False,
        "startup_priority": 11,
        "capabilities": ["snapshot-writer"],
    },
]

# ── Lifecycle Policy Abstraction ──────────────────────────────────────────
class ILifecyclePolicy(ABC):
    @abstractmethod
    def determine_state(self, current_time: datetime) -> str:
        """Evaluate the expected lifecycle state (e.g. OFFLINE, TRADING_IDLE, TRADING_LIVE) for the given time."""
        pass

    @abstractmethod
    def next_scheduled_transition(self, current_time: datetime) -> datetime:
        """Calculate the datetime of the next scheduled state transition."""
        pass

class StandardNSEMarketPolicy(ILifecyclePolicy):
    """Orchestrates NSE-specific trading session lifecycle logic."""
    
    def determine_state(self, current_time: datetime) -> str:
        if not is_trading_day(current_time):
            return "OFFLINE"
            
        t = current_time.time()
        start_time = dtime(9, 15, 0)
        end_time = dtime(15, 30, 0)
        
        if start_time <= t < end_time:
            return "TRADING_LIVE"
        else:
            return "TRADING_IDLE"

    def next_scheduled_transition(self, current_time: datetime) -> datetime:
        if not is_trading_day(current_time):
            return self._next_market_open(current_time)

        t = current_time.time()
        if t < dtime(9, 15, 0):
            return datetime.combine(current_time.date(), dtime(9, 15, 0))
        if t < dtime(15, 30, 0):
            return datetime.combine(current_time.date(), dtime(15, 30, 0))
            
        return self._next_market_open(current_time)

    def _next_market_open(self, current_time: datetime) -> datetime:
        next_day = (current_time + timedelta(days=1)).date()
        while not is_trading_day(next_day):
            next_day += timedelta(days=1)
        return datetime.combine(next_day, dtime(9, 15, 0))

datetime_shim = datetime

# ── Lifecycle Manager ─────────────────────────────────────────────────────
class LifecycleManager:
    """Manages startup, state transitions, and process monitoring for microservices."""
    
    def __init__(self, services: List[Dict], lifecycle_policy: Optional[ILifecyclePolicy] = None):
        self.services = services
        self.lifecycle_policy = lifecycle_policy or StandardNSEMarketPolicy()
        
        self.processes: Dict[str, subprocess.Popen] = {}
        self.restart_counts: Dict[str, int] = {}
        self.restart_timestamps: Dict[str, List[float]] = {}
        self.log_handles: Dict[str, Any] = {}
        self._shutdown = False
        
        self.current_state = "UNKNOWN"
        self.system_health = "STARTING"
        self.transition_history = deque(maxlen=500)
        self.shutdown_manager = ShutdownManager()
        # RuntimeTelemetryAggregator is now a supervised external service
        # (live_fix_aggregator.py) — use a no-op stub here to preserve
        # call sites without running a competing in-process writer.
        class _NoOpAggregator:
            listener_thread = None
            writer_thread = None
            def start(self): pass
            def stop(self): pass
        self.telemetry_aggregator = _NoOpAggregator()
        self.peak_cpu = 0.0
        self.peak_ram = 0.0
        self.last_peak_reset = datetime_mod.datetime.now().date()
        self.runtime_validation = {}
        
        self.service_status: Dict[str, Dict[str, Any]] = {
            svc["name"]: {
                "name": svc["name"],
                "command": svc["command"],
                "role": svc.get("role", "SYSTEM"),
                "state": "pending",
                "pid": None,
                "return_code": None,
                "restarts": 0,
                "last_update": None,
            }
            for svc in services
        }
        
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)

    def _write_pid_file(self):
        try:
            with open(PID_FILE, "w", encoding="utf-8") as f:
                f.write(str(os.getpid()))
        except Exception as exc:
            logger.warning("Unable to write PID file: %s", exc)

    def _remove_pid_file(self):
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
        except Exception as exc:
            logger.warning("Unable to remove PID file: %s", exc)

    def _run_runtime_validation(self) -> dict:
        validation = {}
        
        # 1. Disk Space
        try:
            disk = psutil.disk_usage(os.path.dirname(SERVICE_STATUS_FILE))
            free_gb = disk.free / (1024**3)
            validation["disk_space"] = "PASS" if free_gb > 1.0 else ("WARNING" if free_gb > 0.1 else "FAIL")
        except Exception:
            validation["disk_space"] = "FAIL"
            
        # 2. SQLite Status
        try:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "instruments.db")
            if os.path.exists(db_path):
                import sqlite3
                conn = sqlite3.connect(db_path, timeout=1.0)
                conn.execute("SELECT name FROM sqlite_master LIMIT 1")
                conn.close()
                validation["sqlite_status"] = "PASS"
            else:
                validation["sqlite_status"] = "WARNING"
        except Exception:
            validation["sqlite_status"] = "FAIL"
            
        # 3. Runtime Folder
        try:
            runtime_dir = os.path.dirname(SERVICE_STATUS_FILE)
            test_file = os.path.join(runtime_dir, ".runtime_test")
            with open(test_file, "w") as f:
                f.write("test")
            os.remove(test_file)
            validation["runtime_folder"] = "PASS"
        except Exception:
            validation["runtime_folder"] = "FAIL"
            
        # 4. Broker Connectivity Config
        env_keys = ["ANGEL_API_KEY", "ANGEL_CLIENT_ID", "ANGEL_PASSWORD", "ANGEL_TOTP_SECRET"]
        has_creds = all(os.environ.get(k) or os.getenv(k) for k in env_keys)
        validation["broker_connectivity"] = "PASS" if has_creds else "WARNING"
        
        # 5. Service Health
        any_failed = False
        for name, status in self.service_status.items():
            svc_def = next((s for s in self.services if s["name"] == name), None)
            if svc_def and not svc_def.get("enabled", True):
                continue
            if status.get("state") in ["failed", "exited"] and status.get("return_code", 0) != 0:
                any_failed = True
                break
        validation["service_health"] = "FAIL" if any_failed else "PASS"
        
        # 6. ZMQ Health
        zmq_ports = [5555, 5556]
        zmq_ok = True
        for port in zmq_ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                try:
                    s.connect(("127.0.0.1", port))
                except Exception:
                    if self.current_state in ["TRADING_LIVE", "TRADING_IDLE"]:
                        zmq_ok = False
        validation["zmq_health"] = "PASS" if zmq_ok else "WARNING"
        
        # 7. Flask Health
        flask_ok = False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            try:
                s.connect(("127.0.0.1", 5000))
                flask_ok = True
            except Exception:
                pass
        validation["flask_health"] = "PASS" if flask_ok else "WARNING"
        
        return validation

    def _collect_child_metrics(self):
        self.runtime_validation = self._run_runtime_validation()
        
        for name, proc in list(self.processes.items()):
            status = self.service_status.get(name)
            if status is None:
                continue
            
            if proc is not None and proc.poll() is None:
                try:
                    p = psutil.Process(proc.pid)
                    status["cpu_percent"] = p.cpu_percent(interval=None)
                    status["memory_mb"] = round(p.memory_info().rss / (1024 * 1024), 2)
                    status["thread_count"] = p.num_threads()
                    uptime_seconds = time.time() - p.create_time()
                    status["uptime_seconds"] = round(uptime_seconds, 1)
                except Exception:
                    status["cpu_percent"] = 0.0
                    status["memory_mb"] = 0.0
                    status["thread_count"] = 0
                    status["uptime_seconds"] = 0.0
            else:
                status["cpu_percent"] = 0.0
                status["memory_mb"] = 0.0
                status["thread_count"] = 0
                status["uptime_seconds"] = 0.0

    def _persist_status(self):
        try:
            total_cpu = psutil.cpu_percent(interval=None)
            total_ram = psutil.virtual_memory().percent
            
            # Platform CPU (Supervisor + children)
            platform_cpu = 0.0
            try:
                supervisor_proc = psutil.Process(os.getpid())
                platform_cpu += supervisor_proc.cpu_percent(interval=None)
            except Exception:
                pass
                
            for name, proc in self.processes.items():
                if proc is not None and proc.poll() is None:
                    try:
                        p = psutil.Process(proc.pid)
                        platform_cpu += p.cpu_percent(interval=None)
                    except Exception:
                        pass
            
            today = datetime_mod.datetime.now().date()
            if self.last_peak_reset != today:
                self.peak_cpu = 0.0
                self.peak_ram = 0.0
                self.last_peak_reset = today
                
            self.peak_cpu = max(self.peak_cpu, total_cpu)
            self.peak_ram = max(self.peak_ram, total_ram)
            
            total_threads = psutil.Process(os.getpid()).num_threads()
            for name, proc in self.processes.items():
                if proc is not None and proc.poll() is None:
                    try:
                        total_threads += psutil.Process(proc.pid).num_threads()
                    except Exception: pass
        except Exception:
            total_cpu = 0.0
            platform_cpu = 0.0
            total_ram = 0.0
            total_threads = 1

        status_payload = {
            "schema_version": "2.0.0",
            "platform_version": "1.0.0",
            "generated_at": datetime_mod.datetime.now().isoformat(),
            "engine_pid": os.getpid(),
            "lifecycle_state": self.current_state,
            "system_health": self.system_health,
            "last_update": datetime_mod.datetime.now().isoformat(),
            "system_performance": {
                "system_cpu_percent": total_cpu,
                "platform_cpu_percent": round(platform_cpu, 1),
                "total_ram_percent": total_ram,
                "peak_cpu_percent": self.peak_cpu,
                "peak_ram_percent": self.peak_ram,
                "process_count": len([p for p in self.processes.values() if p.poll() is None]) + 1,
                "thread_count": total_threads
            },
            "runtime_validation": self.runtime_validation,
            "services": self.service_status
        }
        logger.debug("Persisting service status to %s (engine PID %s)", SERVICE_STATUS_FILE, os.getpid())
        try:
            write_envelope_json_atomic(SERVICE_STATUS_FILE, status_payload)
        except Exception as exc:
            logger.warning("Unable to write service status file: %s", exc)

    def _update_service_status(self, name: str, state: str, pid: Optional[int] = None, return_code: Optional[int] = None):
        status = self.service_status.get(name)
        if status is None:
            return
        status["state"] = state
        if pid is not None:
            status["pid"] = pid
        if return_code is not None:
            status["return_code"] = return_code
        status["restarts"] = self.restart_counts.get(name, 0)
        status["last_update"] = datetime.now().isoformat()
        self._persist_status()
        # Log the full service status after each update for debugging
        logger.debug("[start_all] Service status after update: %s", self.service_status)

    def _evaluate_system_health(self) -> None:
        """Determines health based on critical vs non-critical services."""
        health = "RUNNING"
        for svc in self.services:
            if not svc.get("enabled", True):
                continue
                
            name = svc["name"]
            status = self.service_status.get(name, {})
            # Only check services active in the current state
            if self._is_role_active_in_state(svc.get("role", "SYSTEM"), self.current_state):
                if status.get("state") in ("failed", "stopped", "exited"):
                    if svc.get("critical", False):
                        health = "FAILED"
                        break
                    else:
                        health = "DEGRADED"
                        
        self.system_health = health
        self._persist_status()

    def _is_role_active_in_state(self, role: str, state: str) -> bool:
        policies = {
            "TRADING_LIVE": {"TRADING", "UI", "SYSTEM", "SCHEDULER"},
            "TRADING_IDLE": {"UI", "SYSTEM", "SCHEDULER"},
            "OFFLINE": {"UI", "SYSTEM", "SCHEDULER"}
        }
        return role in policies.get(state, set())

    def start_service(self, name: str, command: List[str]):
        """Start a single service using ProcessLauncher for hidden windows."""
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

            log_path = os.path.join(LOGS_DIR, f"{name}.log")
            log_handle = open(log_path, "a", encoding="utf-8")
            self.log_handles[name] = log_handle

            proc = ProcessLauncher.spawn(
                command,
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            self.processes[name] = proc
            self.restart_counts.setdefault(name, 0)
            self._update_service_status(name, "running", pid=proc.pid)
            logger.info("Started %s (PID %d)", name, proc.pid)
        except Exception as exc:
            self._update_service_status(name, "failed", return_code=-1)
            logger.error("Failed to start %s: %s", name, exc)

    def transition_to_state(self, new_state: str, reason: str) -> None:
        """Triggered only on a state change to align processes with allowed roles."""
        prev = self.current_state
        self.current_state = new_state
        
        # Log transition in bounded history
        self.transition_history.append({
            "previous_state": prev,
            "current_state": new_state,
            "timestamp": datetime.now().isoformat(),
            "reason": reason
        })
        
        logger.info(f"Lifecycle Transition: {prev} -> {new_state} (Reason: {reason})")
        
        # 1. Stop disallowed services
        for svc in self.services:
            name = svc["name"]
            role = svc.get("role", "SYSTEM")
            if not self._is_role_active_in_state(role, new_state):
                proc = self.processes.get(name)
                if proc and proc.poll() is None:
                    logger.info("Stopping %s (role %s inactive in state %s)", name, role, new_state)
                    self._stop_service_proc(name, proc)

        # 2. Start allowed, enabled services sorted by priority (highest first)
        sorted_services = sorted(self.services, key=lambda s: s.get("startup_priority", 0), reverse=True)
        for svc in sorted_services:
            if not svc.get("enabled", True):
                continue
                
            name = svc["name"]
            role = svc.get("role", "SYSTEM")
            if self._is_role_active_in_state(role, new_state):
                proc = self.processes.get(name)
                if not proc or proc.poll() is not None:
                    self.start_service(name, svc["command"])

        self._evaluate_system_health()

    def _stop_service_proc(self, name: str, proc: subprocess.Popen) -> None:
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("%s did not terminate; killing.", name)
            proc.kill()
        except Exception as exc:
            logger.error("Error stopping %s: %s", name, exc)
        finally:
            self.processes.pop(name, None)
            self._update_service_status(name, "stopped", pid=getattr(proc, 'pid', None), return_code=proc.returncode)

    def start_all(self):
        """Standard NSE boot logic - resolves the state and transitions accordingly."""
        # Start Telemetry Aggregator helper
        try:
            self.telemetry_aggregator.start()
        except Exception as e:
            logger.error("Failed to start TelemetryAggregator: %s", e)
            
        now = datetime_shim.now()
        initial_state = self.lifecycle_policy.determine_state(now)
        self.transition_to_state(initial_state, "Engine Startup")

    def handle_restart(self, svc: Dict):
        """Restart a service using exponential backoff inside a rolling window."""
        name = svc["name"]
        now = time.time()
        
        timestamps = self.restart_timestamps.setdefault(name, [])
        timestamps = [ts for ts in timestamps if now - ts < SUPERVISOR_MAX_RESTART_WINDOW_SECONDS]
        self.restart_timestamps[name] = timestamps
        
        count = len(timestamps)
        
        if count >= SUPERVISOR_MAX_RESTARTS:
            logger.error(
                "%s exceeded max restarts (%d) within %ds. Not restarting.",
                name, SUPERVISOR_MAX_RESTARTS, SUPERVISOR_MAX_RESTART_WINDOW_SECONDS
            )
            self._update_service_status(name, "failed")
            self._evaluate_system_health()
            return

        self.restart_timestamps[name].append(now)
        self.restart_counts[name] = count + 1
        self._update_service_status(name, "restarting")

        delay = SUPERVISOR_RESTART_DELAY_SECONDS * (2 ** count)
        
        logger.info("Restarting %s in %ds (attempt %d/%d in window)...",
                    name, delay, count + 1, SUPERVISOR_MAX_RESTARTS)
                    
        # Run restart in a background thread so the monitor loop (and TelemetryAggregator
        # watchdog) is never blocked by the backoff sleep.
        def _do_restart():
            time.sleep(delay)
            self.start_service(name, svc["command"])
        t = threading.Thread(target=_do_restart, name=f"Restart-{name}", daemon=True)
        t.start()

    def monitor(self):
        """Periodic loop to verify running processes, transition aware, avoiding busy-polling."""
        while not self._shutdown:
            # 0. Check for graceful shutdown request via ShutdownManager
            if self.shutdown_manager.is_shutdown_requested():
                logger.info("Graceful shutdown trigger detected via ShutdownManager.")
                self.shutdown_manager.clear_shutdown_trigger()
                self.shutdown()
                break

            # 0b. Watchdog: Restart TelemetryAggregator threads if they have silently died
            try:
                agg = self.telemetry_aggregator
                listener_dead = agg.listener_thread is None or not agg.listener_thread.is_alive()
                writer_dead = agg.writer_thread is None or not agg.writer_thread.is_alive()
                if listener_dead or writer_dead:
                    logger.warning(
                        "TelemetryAggregator threads dead (listener=%s, writer=%s). Restarting...",
                        "dead" if listener_dead else "ok",
                        "dead" if writer_dead else "ok"
                    )
                    try:
                        agg.stop()
                    except Exception:
                        pass
                    import time as _t; _t.sleep(0.5)
                    try:
                        agg.start()
                        logger.info("TelemetryAggregator restarted successfully.")
                    except Exception as e:
                        logger.error("Failed to restart TelemetryAggregator: %s", e)
            except Exception as wdog_err:
                logger.warning("Aggregator watchdog check failed: %s", wdog_err)

            time.sleep(SUPERVISOR_POLLING_INTERVAL_SECONDS)
            
            # 1. Check for scheduled lifecycle state transitions
            now = datetime_shim.now()
            expected_state = self.lifecycle_policy.determine_state(now)
            if expected_state != self.current_state:
                self.transition_to_state(expected_state, "Scheduled transition policy")
                
            # 2. Check status of running processes
            for svc in self.services:
                if not svc.get("enabled", True):
                    continue
                    
                name = svc["name"]
                role = svc.get("role", "SYSTEM")
                
                # We only supervise/check processes that *should* be running
                if self._is_role_active_in_state(role, self.current_state):
                    proc = self.processes.get(name)
                    if proc is None:
                        # Should be running but isn't
                        self.start_service(name, svc["command"])
                        continue
                        
                    retcode = proc.poll()
                    if retcode is None:
                        self._update_service_status(name, "running", pid=proc.pid)
                        continue
                        
                    logger.warning("%s exited with code %d", name, retcode)
                    self._update_service_status(name, "exited", pid=proc.pid, return_code=retcode)
                    
                    policy = svc.get("restart_policy", "on-failure")
                    should_restart = (policy == "always") or (policy == "on-failure" and retcode != 0)
                    
                    if should_restart:
                        self.handle_restart(svc)
                    else:
                        self.processes.pop(name, None)
                        self._update_service_status(name, "stopped", pid=proc.pid, return_code=retcode)
                        
            self._evaluate_system_health()
            self._collect_child_metrics()
            self._persist_status()

    def shutdown(self):
        """Gracefully terminate all running processes."""
        self._shutdown = True
        logger.info("Shutting down all services...")
        
        # Stop Telemetry Aggregator helper
        try:
            self.telemetry_aggregator.stop()
        except Exception as e:
            logger.error("Failed to stop TelemetryAggregator: %s", e)
            
        for name, proc in list(self.processes.items()):
            self._stop_service_proc(name, proc)

        for handle in self.log_handles.values():
            try:
                handle.close()
            except Exception:
                pass
        self.log_handles.clear()
        self._remove_pid_file()
        logger.info("All services stopped.")

# Backward-compatibility shim – legacy tests expect ``ProcessSupervisor``.
ProcessSupervisor = LifecycleManager

# ── Signal handlers ───────────────────────────────────────────────────────────
supervisor: Optional[LifecycleManager] = None

def handle_shutdown(signum, frame):
    global supervisor
    logger.info("Received signal %d. Shutting down...", signum)
    if supervisor:
        supervisor.shutdown()
    sys.exit(0)

def main():
    global supervisor
    logger.info("------------------------------------------------------------------------")
    logger.info("|      Options Quant Algo - Start All Services                         |")
    logger.info("------------------------------------------------------------------------")

    # ---------------------------------------------------------------------
    # Pre‑engine broker validation
    # ---------------------------------------------------------------------
    validation_result = run_broker_validation()
    if validation_result.get("status") != "PASS":
        # Summarize failures for the operator and abort engine start.
        failed = [step for step, info in validation_result.get("details", {}).items()
                  if isinstance(info, dict) and info.get("status") == "FAIL"]
        logger.error("Broker validation failed for %s. Engine start aborted.", validation_result.get("broker"))
        if failed:
            logger.error("Failed capabilities: %s", ", ".join(failed))
        # Ensure the environment remains on the safe fallback broker.
        sys.exit(1)

    # Failsafe: Initialize Universal Instrument Registry if empty
    try:
        from src.core.instrument_repository import InstrumentRepository
        repo = InstrumentRepository()
        if repo.get_count() == 0:
            logger.info("Universal Instrument Registry is empty. Initializing sync...")
            from src.services.instrument_sync_service import run_sync
            run_sync(force=True)
    except Exception as sync_exc:
        logger.error(f"Failsafe Instrument Sync failed: {sync_exc}")

    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    supervisor = LifecycleManager(SERVICES)
    supervisor._write_pid_file()
    supervisor.start_all()

    try:
        supervisor.monitor()
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        supervisor.shutdown()

if __name__ == "__main__":
    main()
