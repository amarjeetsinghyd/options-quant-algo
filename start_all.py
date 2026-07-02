#!/usr/bin/env python3
"""
start_all.py

Orchestration script for the options-quant-algo system.
Launches all services in supervised processes:
  - ResearchCollector (OHLCV data archival)
  - Main trading engine
  - ZMQ message bus
  - DB writer queue

Includes basic watchdog/restart logic and graceful shutdown on SIGINT/SIGTERM.
"""

import json
import os
import sys
import signal
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Any
import datetime as datetime_mod
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
from datetime import timedelta, time as dtime

from src.config.engineering_config import DATA_DIR, LOGS_DIR
from src.utils.logger import get_logger
from src.utils.market_calendar import is_trading_day

logger = get_logger("start_all")

SERVICE_STATUS_FILE = os.path.join(os.path.dirname(__file__), "data", "service_status.json")
PID_FILE = os.path.join(os.path.dirname(__file__), "data", "quant_engine.pid")

# ── Service definitions ───────────────────────────────────────────────────
SERVICES = [
    {
        "name": "feed_service",
        "command": [sys.executable, "src/services/feed_service.py"],
        "restart_on_failure": True,
    },
    {
        "name": "brain_service",
        "command": [sys.executable, "src/services/brain_service.py"],
        "restart_on_failure": True,
    },
    {
        "name": "research_collector",
        "command": [sys.executable, "src/services/research_service.py"],
        "restart_on_failure": True,
    },
    {
        "name": "web_dashboard",
        "command": [sys.executable, "main.py"],
        "restart_on_failure": True,
    },
    {
        "name": "maintenance_service",
        "command": [sys.executable, "src/services/maintenance_service.py"],
        "restart_on_failure": True,
    },
    {
        "name": "gap_fill_service",
        "command": [sys.executable, "src/services/gap_fill_service.py"],
        "restart_on_failure": True,
    },
    {
        "name": "health_monitor",
        "command": [sys.executable, "src/services/health_service.py"],
        "restart_on_failure": True,
    },
    {
        "name": "decision_journal",
        "command": [sys.executable, "src/services/decision_journal.py"],
        "restart_on_failure": True,
    },
    {
        "name": "shadow_service",
        "command": [sys.executable, "src/services/shadow_service.py"],
        "restart_on_failure": True,
    },
    {
        "name": "cloud_backup",
        "command": [sys.executable, "src/services/cloud_backup.py"],
        "restart_on_failure": True,
    },
]

RESTART_DELAY_SECONDS = 5
MAX_RESTARTS = 3
MAX_RESTART_WINDOW_SECONDS = 300


class ProcessSupervisor:
    """
    Simple process supervisor with restart logic.
    Maintains running subprocesses and restarts them on failure.
    """

    def __init__(self, services: List[Dict]):
        self.services = services
        self.processes: Dict[str, subprocess.Popen] = {}
        self.restart_counts: Dict[str, int] = {}
        self.restart_timestamps: Dict[str, List[float]] = {}
        self._shutdown = False
        self.log_handles: Dict[str, Any] = {}
        self.service_status: Dict[str, Dict[str, Any]] = {
            svc["name"]: {
                "name": svc["name"],
                "command": svc["command"],
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

    def start_all(self):
        """Restart all services after an idle period.

        In production this delegates to the module‑level ``start_all`` function
        which creates a fresh ``ProcessSupervisor`` and begins monitoring.
        The method exists primarily to allow tests to monkey‑patch and verify
        that the idle path triggers a restart.
        """
        # Call the top‑level ``start_all`` function without causing recursion.
        globals()["start_all"]()

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

    def _persist_status(self):
        status_payload = {
            "engine_pid": os.getpid(),
            "started_at": datetime_mod.datetime.now().isoformat(),
            "services": self.service_status,
            "last_update": datetime_mod.datetime.now().isoformat(),
        }
        try:
            with open(SERVICE_STATUS_FILE, "w", encoding="utf-8") as f:
                json.dump(status_payload, f, indent=2)
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
        status["last_update"] = datetime_mod.datetime.now().isoformat()
        self._persist_status()

    def start_all(self):
        """Launch all services."""
        for svc in self.services:
            self.start_service(svc["name"], svc["command"])

    def start_service(self, name: str, command: List[str]):
        """Start a single service."""
        try:
            env = os.environ.copy()
            env["PYTHONPATH"] = os.path.dirname(os.path.abspath(__file__))

            log_path = os.path.join(LOGS_DIR, f"{name}.log")
            log_handle = open(log_path, "a", encoding="utf-8")
            self.log_handles[name] = log_handle

            proc = subprocess.Popen(
                command,
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            )
            self.processes[name] = proc
            self.restart_counts.setdefault(name, 0)
            self._update_service_status(name, "running", pid=proc.pid)
            logger.info("Started %s (PID %d)", name, proc.pid)
        except Exception as exc:
            self._update_service_status(name, "failed", return_code=-1)
            logger.error("Failed to start %s: %s", name, exc)

    def monitor(self):
        """
        Poll all processes. Restart if a process exits and restart is enabled.
        """
        while not self._shutdown:
            time.sleep(2)
            for svc in self.services:
                name = svc["name"]
                proc = self.processes.get(name)
                if proc is None:
                    continue

                retcode = proc.poll()
                if retcode is None:
                    self._update_service_status(name, "running", pid=proc.pid)
                    continue

                logger.warning("%s exited with code %d", name, retcode)
                self._update_service_status(name, "stopped", pid=proc.pid, return_code=retcode)
                if svc.get("restart_on_failure", False):
                    self.handle_restart(svc)
                else:
                    del self.processes[name]

            # Autonomous Shutdown at Configured Time – replaced with idle wait until next market session
            now = datetime_mod.datetime.now()
            from src.config.engineering_config import MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE
            if now.hour > MARKET_CLOSE_HOUR or (now.hour == MARKET_CLOSE_HOUR and now.minute >= MARKET_CLOSE_MINUTE):
                logger.info(f"Market Closed ({MARKET_CLOSE_HOUR}:{MARKET_CLOSE_MINUTE:02d}). Entering idle until next session.")
                # Gracefully stop all services
                self.shutdown()
                # Compute next market open datetime and sleep until then
                next_open = self._next_market_open()
                sleep_seconds = max(0, (next_open - datetime.now()).total_seconds())
                logger.info(f"Sleeping for {sleep_seconds/60:.1f} minutes until next market open at {next_open}.")
                # Sleep without blocking the whole process for a long time – use a short loop to remain responsive to shutdown signals
                slept = 0
                while slept < sleep_seconds and not self._shutdown:
                    interval = min(30, sleep_seconds - slept)  # sleep in 30‑second chunks
                    time.sleep(interval)
                    slept += interval
                # After waking, restart all services for the new session
                logger.info("Waking up for new trading session – restarting services.")
                self.start_all()
                # If a shutdown was requested during idle, exit the monitor loop now.
                if self._shutdown:
                    break
                continue

    def _next_market_open(self) -> datetime:
        """Calculate the next market open datetime (09:15) on a trading day.

        The method starts checking from the day after the current date and
        iterates forward until ``is_trading_day`` returns ``True`` for the date.
        It then returns a ``datetime`` combining that date with the market open
        time (09:15). This logic is used by the idle loop after market close
        to determine how long to sleep before restarting services.
        """
        # Start checking from the next calendar day
        next_day = (datetime_mod.datetime.now() + timedelta(days=1)).date()
        # Find the next date that is a trading day according to the helper
        while not is_trading_day(next_day):
            next_day += timedelta(days=1)
        # Market opens at 09:15 local time
        return datetime_mod.datetime.combine(next_day, dtime(hour=9, minute=15))

    def handle_restart(self, svc: Dict):
        """Restart a service using exponential backoff inside a rolling window."""
        name = svc["name"]
        now = time.time()
        
        timestamps = self.restart_timestamps.setdefault(name, [])
        timestamps = [ts for ts in timestamps if now - ts < MAX_RESTART_WINDOW_SECONDS]
        self.restart_timestamps[name] = timestamps
        
        count = len(timestamps)
        
        if count >= MAX_RESTARTS:
            logger.error(
                "%s exceeded max restarts (%d) within %ds. Not restarting.",
                name, MAX_RESTARTS, MAX_RESTART_WINDOW_SECONDS
            )
            self._update_service_status(name, "failed")
            return

        self.restart_timestamps[name].append(now)
        self.restart_counts[name] = count + 1
        self._update_service_status(name, "restarting")

        delay = RESTART_DELAY_SECONDS * (2 ** count)
        
        logger.info("Restarting %s in %ds (attempt %d/%d in window)...",
                    name, delay, count + 1, MAX_RESTARTS)
        time.sleep(delay)
        self.start_service(name, svc["command"])

    def shutdown(self):
        """Gracefully terminate all running processes."""
        self._shutdown = True
        logger.info("Shutting down all services...")
        for name, proc in list(self.processes.items()):
            try:
                if proc.poll() is None:
                    logger.info("Terminating %s (PID %d)", name, proc.pid)
                    proc.terminate()
                    proc.wait(timeout=10)
                else:
                    logger.info("%s already stopped (PID %d).", name, proc.pid)
            except subprocess.TimeoutExpired:
                logger.warning("%s did not terminate; killing.", name)
                proc.kill()
            except Exception as exc:
                logger.error("Error stopping %s: %s", name, exc)
            finally:
                self._update_service_status(name, "stopped", pid=getattr(proc, 'pid', None), return_code=proc.returncode)

        for handle in self.log_handles.values():
            try:
                handle.close()
            except Exception:
                pass
        self.log_handles.clear()
        self._remove_pid_file()
        logger.info("All services stopped.")


# ── Signal handlers ───────────────────────────────────────────────────────────
supervisor: Optional[ProcessSupervisor] = None


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

    # Autonomous Boot Check: Is it a trading day?
    if not is_trading_day():
        logger.info("Today is a weekend or public holiday. Engine remaining offline.")
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    supervisor = ProcessSupervisor(SERVICES)
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
