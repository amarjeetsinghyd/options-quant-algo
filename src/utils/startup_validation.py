import os
import sys
import socket
import json
from src.utils.file_utils import write_envelope_json_atomic
import psutil
from pathlib import Path
from datetime import datetime

SCHEMA_VERSION = "2.0.0"
PLATFORM_VERSION = "1.0.0"

def check_port_free(port: int) -> bool:
    """Checks if a local TCP port is free to bind."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except socket.error:
            return False

def run_startup_validation(base_dir: Path) -> dict:
    """Performs a one-off startup validation check suite."""
    report = {}
    overall_status = "PASS"
    
    # 1. Python Environment
    py_ver = sys.version_info
    if py_ver.major == 3 and py_ver.minor >= 8:
        report["python_env"] = {"status": "PASS", "details": f"Python {sys.version.split()[0]}"}
    else:
        report["python_env"] = {"status": "FAIL", "details": f"Python version {sys.version.split()[0]} is unsupported (requires >= 3.8)"}
        overall_status = "FAIL"

    # 2. Virtual Environment
    is_venv = sys.prefix != sys.base_prefix or "VIRTUAL_ENV" in os.environ
    if is_venv:
        report["venv"] = {"status": "PASS", "details": "Virtual Environment Active"}
    else:
        report["venv"] = {"status": "WARNING", "details": "Not running in a Virtual Environment"}
        if overall_status == "PASS":
            overall_status = "WARNING"

    # 3. Configuration
    env_file = base_dir / ".env"
    if env_file.exists():
        report["config"] = {"status": "PASS", "details": ".env file detected"}
    else:
        report["config"] = {"status": "FAIL", "details": ".env file missing"}
        overall_status = "FAIL"

    # 4. Database
    db_file = base_dir / "data" / "instruments.db"
    if db_file.exists():
        try:
            # Check if readable
            with open(db_file, "rb") as f:
                f.read(100)
            report["database"] = {"status": "PASS", "details": "instruments.db detected and readable"}
        except Exception as e:
            report["database"] = {"status": "FAIL", "details": f"instruments.db read error: {e}"}
            overall_status = "FAIL"
    else:
        report["database"] = {"status": "WARNING", "details": "instruments.db missing (will auto-initialize)"}
        if overall_status == "PASS":
            overall_status = "WARNING"

    # 5. Runtime Folder
    runtime_dir = base_dir / "runtime"
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        test_file = runtime_dir / ".write_test"
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("test")
        test_file.unlink()
        report["runtime_folder"] = {"status": "PASS", "details": "runtime/ directory writable"}
    except Exception as e:
        report["runtime_folder"] = {"status": "FAIL", "details": f"runtime/ directory read/write failure: {e}"}
        overall_status = "FAIL"

    # 6. Broker Connection Config
    broker_keys = ["SHOONYA_USER_ID", "SHOONYA_PASSWORD", "SHOONYA_API_KEY"]
    has_credentials = True
    for key in broker_keys:
        if not os.environ.get(key) and not os.getenv(key):
            # Try parsing .env manually if not loaded in environment
            if env_file.exists():
                with open(env_file, "r") as f:
                    content = f.read()
                    if key not in content:
                        has_credentials = False
            else:
                has_credentials = False
                
    if has_credentials:
        report["broker_config"] = {"status": "PASS", "details": "Broker configuration credentials set"}
    else:
        report["broker_config"] = {"status": "WARNING", "details": "Missing broker credentials in environment or .env"}
        if overall_status == "PASS":
            overall_status = "WARNING"

    # 7. Disk Space
    try:
        disk = psutil.disk_usage(str(base_dir))
        free_gb = disk.free / (1024 ** 3)
        if free_gb > 1.0:
            report["disk_space"] = {"status": "PASS", "details": f"{free_gb:.2f} GB free disk space"}
        elif free_gb > 0.1:
            report["disk_space"] = {"status": "WARNING", "details": f"Low disk space: {free_gb:.2f} GB free"}
            if overall_status == "PASS":
                overall_status = "WARNING"
        else:
            report["disk_space"] = {"status": "FAIL", "details": f"Critical disk space: {free_gb:.2f} GB free"}
            overall_status = "FAIL"
    except Exception as e:
        report["disk_space"] = {"status": "WARNING", "details": f"Failed to check disk: {e}"}

    # 8. Port Availability
    ports_to_check = [5000, 5555, 5556] # Flask, ZMQ Feed, ZMQ Exec
    port_conflict = []
    for port in ports_to_check:
        if not check_port_free(port):
            port_conflict.append(port)
            
    if not port_conflict:
        report["port_availability"] = {"status": "PASS", "details": "All required ports (5000, 5555, 5556) are available"}
    else:
        report["port_availability"] = {"status": "WARNING", "details": f"Ports currently in use: {port_conflict}"}
        if overall_status == "PASS":
            overall_status = "WARNING"

    # Wrap up report with schemas
    final_report = {
        "schema_version": SCHEMA_VERSION,
        "platform_version": PLATFORM_VERSION,
        "generated_at": datetime.now().isoformat(),
        "overall_status": overall_status,
        "checks": report
    }
    
    # Save report
    report_file = str(runtime_dir / "platform_validation.json")
    try:
        write_envelope_json_atomic(report_file, final_report)
    except Exception as e:
        print(f"Failed to write platform validation atomically: {e}")
        
    return final_report
