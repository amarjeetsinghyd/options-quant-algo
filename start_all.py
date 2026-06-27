# start_all.py
# QuantOS Runtime — Service Orchestrator
# Phase 6.2 — Lean Microservices
# Governed by: DOC-1.2 Engineering Optimization Roadmap (ASD v1)
#
# Active services (per engineering_config.py):
#   1. feed_service.py       — Market data feed (ZMQ publisher)
#   2. brain_service.py      — Signal generation + execution logic
#   3. research_collector.py — Parquet journal (data collection)
#   4. main.py               — Flask web dashboard
#
# Disabled services (auto-exit via flag guard):
#   - shadow_service.py      — ENABLE_SHADOW_SERVICE=False

import subprocess
import sys
import time
import os

try:
    from src.config.engineering_config import (
        ENABLE_SHADOW_SERVICE,
        ENABLE_RESEARCH_COLLECTOR,
        ENABLE_WEB_DASHBOARD,
    )
except ImportError:
    ENABLE_SHADOW_SERVICE = False
    ENABLE_RESEARCH_COLLECTOR = True
    ENABLE_WEB_DASHBOARD = True


def main():
    print("=== QUANT TERMINAL MICROSERVICES STARTUP ===")
    print(f"  shadow_service : {'ENABLED' if ENABLE_SHADOW_SERVICE else 'DISABLED (per DOC-1.2)'}")
    print(f"  research_collector : {'ENABLED' if ENABLE_RESEARCH_COLLECTOR else 'DISABLED'}")
    print(f"  web_dashboard  : {'ENABLED' if ENABLE_WEB_DASHBOARD else 'DISABLED'}")
    print()

    # Ensure logs and data directories exist
    os.makedirs("logs", exist_ok=True)
    os.makedirs(os.path.join("data", "research_journal"), exist_ok=True)

    processes = []

    try:
        # 1. Feed Service (Market Data — must start first)
        print("[start_all] Starting Feed Service (market data)...")
        p_feed = subprocess.Popen([sys.executable, "src/services/feed_service.py"])
        processes.append(("feed_service", p_feed))
        time.sleep(2)  # Wait for ZMQ port to bind

        # 2. Brain Service (Signal + Execution Logic)
        print("[start_all] Starting Brain Service (signal/execution)...")
        p_brain = subprocess.Popen([sys.executable, "src/services/brain_service.py"])
        processes.append(("brain_service", p_brain))
        time.sleep(2)

        # 3. Research Collector (Parquet journal — enabled in this phase)
        if ENABLE_RESEARCH_COLLECTOR:
            print("[start_all] Starting Research Collector (Parquet journal)...")
            p_rc = subprocess.Popen([sys.executable, "src/services/research_collector.py"])
            processes.append(("research_collector", p_rc))
            time.sleep(1)
        else:
            print("[start_all] Research Collector DISABLED — skipping.")

        # 4. Shadow Service (self-exits if ENABLE_SHADOW_SERVICE=False)
        if ENABLE_SHADOW_SERVICE:
            print("[start_all] Starting Shadow Service (ML predictor)...")
            p_shadow = subprocess.Popen([sys.executable, "src/services/shadow_service.py"])
            processes.append(("shadow_service", p_shadow))
            time.sleep(1)
        else:
            print("[start_all] Shadow Service DISABLED per DOC-1.2 — skipping.")

        # 5. Web Dashboard (Flask)
        if ENABLE_WEB_DASHBOARD:
            print("[start_all] Starting Web Dashboard (Flask)...")
            p_ui = subprocess.Popen([sys.executable, "main.py"])
            processes.append(("web_dashboard", p_ui))

        print()
        print("[start_all] All services started. Press Ctrl+C to stop.")
        print(f"[start_all] Active processes: {[name for name, _ in processes]}")
        print()

        # Wait indefinitely until interrupted
        for name, p in processes:
            p.wait()

    except KeyboardInterrupt:
        print()
        print("[start_all] Ctrl+C received — shutting down all services...")
        for name, p in processes:
            print(f"[start_all] Terminating {name}...")
            p.terminate()
        for name, p in processes:
            p.wait()
        print("[start_all] Shutdown complete.")
        sys.exit(0)


if __name__ == "__main__":
    main()
