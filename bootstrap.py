import os
import sys
import psutil
from pathlib import Path

# Paths Setup
BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR = BASE_DIR / "runtime"
LOGS_DIR = BASE_DIR / "logs"
PID_FILE = RUNTIME_DIR / "quant_engine.pid"

def check_and_acquire_lock() -> bool:
    """Verifies that no other instance of the quant-engine is currently running."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    
    if PID_FILE.exists():
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                old_pid = int(f.read().strip())
            
            # Check if process is running
            if psutil.pid_exists(old_pid):
                proc = psutil.Process(old_pid)
                # Confirm it is a python instance (prevents clash if PID was recycled by unrelated app)
                if "python" in proc.name().lower():
                    print(f"[bootstrap] ERROR: Engine is already running under PID {old_pid}.", file=sys.stderr)
                    return False
        except (ValueError, psutil.NoSuchProcess, psutil.AccessDenied):
            pass
            
    # Acquire Lock: Write current PID
    with open(PID_FILE, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    return True

def redirect_stdout_stderr():
    """Redirects stdout and stderr to files if running in windowless pythonw.exe mode."""
    # pythonw.exe has sys.executable ending with pythonw.exe and sys.stdout is None
    is_windowless = sys.stdout is None or "pythonw.exe" in sys.executable.lower()
    
    if is_windowless:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        stdout_log = LOGS_DIR / "quant_engine_stdout.log"
        stderr_log = LOGS_DIR / "quant_engine_stderr.log"
        
        sys.stdout = open(stdout_log, "a", encoding="utf-8", buffering=1)
        sys.stderr = open(stderr_log, "a", encoding="utf-8", buffering=1)
        print("\n--- Daemon Started ---")

def main():
    if not check_and_acquire_lock():
        sys.exit(1)
        
    redirect_stdout_stderr()
    
    print(f"[bootstrap] Starting Quant Engine Supervisor (PID {os.getpid()})...")
    
    # Import and run start_all
    sys.path.insert(0, str(BASE_DIR))
    import start_all
    start_all.main()

if __name__ == "__main__":
    main()
