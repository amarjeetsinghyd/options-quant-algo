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

import os
import sys
import signal
import time
import subprocess
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime

from src.utils.logger import get_logger
from src.utils.market_calendar import is_trading_day

logger = get_logger("start_all")

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
        "name": "shadow_service",
        "command": [sys.executable, "src/services/shadow_service.py"],
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
        "name": "health_monitor",
        "command": [sys.executable, "src/services/health_service.py"],
        "restart_on_failure": True,
    },
    {
        "name": "decision_journal",
        "command": [sys.executable, "src/services/decision_journal.py"],
        "restart_on_failure": True,
    },
]

RESTART_DELAY_SECONDS = 5
MAX_RESTARTS = 3


class ProcessSupervisor:
    """
    Simple process supervisor with restart logic.
    Maintains running subprocesses and restarts them on failure.
    """

    def __init__(self, services: List[Dict]):
        self.services = services
        self.processes: Dict[str, subprocess.Popen] = {}
        self.restart_counts: Dict[str, int] = {}
        self._shutdown = False

    def start_all(self):
        """Launch all services."""
        for svc in self.services:
            self.start_service(svc["name"], svc["command"])

    def start_service(self, name: str, command: List[str]):
        """Start a single service."""
        try:
            proc = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            self.processes[name] = proc
            self.restart_counts.setdefault(name, 0)
            logger.info("Started %s (PID %d)", name, proc.pid)
        except Exception as exc:
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
                if retcode is not None:
                    logger.warning("%s exited with code %d", name, retcode)
                    if svc.get("restart_on_failure", False):
                        self.handle_restart(svc)
                    else:
                        del self.processes[name]

            # Autonomous 4:00 PM Shutdown
            now = datetime.now()
            if now.hour >= 16:
                logger.info("Market Closed (4:00 PM). Autonomous Shutdown Initiated.")
                self.shutdown()
                break

    def handle_restart(self, svc: Dict):
        """Restart a service if it hasn't exceeded max restarts."""
        name = svc["name"]
        count = self.restart_counts.get(name, 0)
        if count >= MAX_RESTARTS:
            logger.error(
                "%s exceeded max restarts (%d). Not restarting.",
                name, MAX_RESTARTS
            )
            return

        self.restart_counts[name] = count + 1
        logger.info("Restarting %s in %ds (attempt %d/%d)...",
                    name, RESTART_DELAY_SECONDS, count + 1, MAX_RESTARTS)
        time.sleep(RESTART_DELAY_SECONDS)
        self.start_service(name, svc["command"])

    def shutdown(self):
        """Gracefully terminate all running processes."""
        self._shutdown = True
        logger.info("Shutting down all services...")
        for name, proc in list(self.processes.items()):
            try:
                logger.info("Terminating %s (PID %d)", name, proc.pid)
                proc.terminate()
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("%s did not terminate; killing.", name)
                proc.kill()
            except Exception as exc:
                logger.error("Error stopping %s: %s", name, exc)
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
    logger.info("┌──────────────────────────────────────────────────────────────────────┐")
    logger.info("│      Options Quant Algo - Start All Services            │")
    logger.info("└──────────────────────────────────────────────────────────────────────┘")

    # Autonomous Boot Check: Is it a trading day?
    if not is_trading_day():
        logger.info("Today is a weekend or public holiday. Engine remaining offline.")
        sys.exit(0)

    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    supervisor = ProcessSupervisor(SERVICES)
    supervisor.start_all()

    try:
        supervisor.monitor()
    except KeyboardInterrupt:
        logger.info("Interrupted by user.")
    finally:
        supervisor.shutdown()


if __name__ == "__main__":
    main()
