import os
import sys
import time
import psutil
from pathlib import Path
from src.core.shutdown_manager import ShutdownManager

BASE_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PID_FILE = BASE_DIR / "runtime" / "quant_engine.pid"

def main():
    print("Initiating Graceful Shutdown...")
    
    if not PID_FILE.exists():
        print("No active PID file found. Engine does not appear to be running.")
        return
        
    try:
        with open(PID_FILE, "r", encoding="utf-8") as f:
            target_pid = int(f.read().strip())
    except Exception as e:
        print(f"Error reading PID file: {e}")
        return
        
    if not psutil.pid_exists(target_pid):
        print(f"Process PID {target_pid} is not running.")
        # Cleanup stale files
        try:
            PID_FILE.unlink()
        except: pass
        return
        
    # Verify it is a Python process
    try:
        proc = psutil.Process(target_pid)
        if "python" not in proc.name().lower():
            print(f"PID {target_pid} is not a Python process. Aborting to prevent killing unrelated task.")
            return
    except Exception as e:
        print(f"Error accessing target process: {e}")
        return
        
    # Trigger Shutdown via file flag
    mgr = ShutdownManager(runtime_dir=str(BASE_DIR / "runtime"))
    print(f"Sending shutdown trigger to process {target_pid}...")
    mgr.request_shutdown()
    
    # Try PM2 stop first (if PM2 is managing the process)
    import subprocess
    try:
        print("Attempting to stop via PM2 (if applicable)...")
        # Use shell=True for windows compat if needed, but pm2 is usually in path
        # On Linux, pm2 is usually a global npm package
        result = subprocess.run(
            "pm2 stop quant-engine", 
            shell=True, capture_output=True, text=True
        )
        if result.returncode == 0 and "quant-engine" in result.stdout:
            print("PM2 successfully intercepted and stopped the engine.")
            mgr.clear_shutdown_trigger()
            try:
                if PID_FILE.exists():
                    PID_FILE.unlink()
            except: pass
            return
    except Exception as e:
        print(f"PM2 stop skipped or failed: {e}")
    
    # Poll for termination (Fallback for local/non-PM2 execution)
    max_wait = 15.0
    wait_interval = 0.5
    waited = 0.0
    
    stopped = False
    while waited < max_wait:
        if not psutil.pid_exists(target_pid):
            stopped = True
            break
        time.sleep(wait_interval)
        waited += wait_interval
        
    if stopped:
        print("Engine stopped gracefully.")
    else:
        print("Graceful shutdown timed out. Sending force-kill signal...")
        try:
            # Recursive kill of the entire supervisor process tree
            parent = psutil.Process(target_pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
            print("Engine process tree terminated forceably.")
        except Exception as kill_err:
            print(f"Error while terminating process: {kill_err}")
            
    # Cleanup files
    mgr.clear_shutdown_trigger()
    try:
        if PID_FILE.exists():
            PID_FILE.unlink()
    except:
        pass

if __name__ == "__main__":
    main()
