import os
import sys
import json
import psutil
from src.core.process_launcher import ProcessLauncher

def is_pm2_daemon_running():
    for p in psutil.process_iter(['name', 'cmdline']):
        try:
            name = p.info['name'].lower() if p.info['name'] else ""
            if "node" in name:
                cmdline = p.info['cmdline']
                if cmdline and any("Daemon.js" in arg for arg in cmdline):
                    return True
        except Exception:
            pass
    return False

def get_pm2_apps():
    try:
        res = ProcessLauncher.run_command("pm2 jlist")
        if res.returncode == 0:
            data = json.loads(res.stdout)
            return [app.get("name") for app in data if app.get("name")]
    except Exception:
        pass
    return []

def main():
    print("Checking PM2 Daemon state...")
    daemon_running = is_pm2_daemon_running()
    
    if daemon_running:
        print("PM2 Daemon is already running. Fetching managed applications...")
        apps = get_pm2_apps()
        print(f"Managed applications: {apps}")
        
        # If there are NO apps, or ONLY "quant-engine" is registered under PM2:
        if not apps or apps == ["quant-engine"]:
            print("No unrelated applications found. Performing safe PM2 daemon reset to ensure hidden context...")
            ProcessLauncher.run_command("pm2 kill")
        else:
            print("Unrelated applications detected. Keeping current PM2 daemon intact to avoid disruption.")
            
    print("Starting Quant Engine via PM2...")
    ProcessLauncher.run_command("pm2 start ecosystem.config.js")
    ProcessLauncher.run_command("pm2 save")
    print("Startup complete.")

if __name__ == "__main__":
    main()
