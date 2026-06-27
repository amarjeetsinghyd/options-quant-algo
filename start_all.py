import subprocess
import sys
import time
import os
import signal

def main():
    print("=== QUANT TERMINAL MICROSERVICES STARTUP ===")
    
    # Ensure logs directory exists
    os.makedirs("logs", exist_ok=True)

    processes = []

    try:
        # Start Feed Service (Market Data)
        print("Starting Feed Service...")
        p_feed = subprocess.Popen([sys.executable, "src/services/feed_service.py"])
        processes.append(p_feed)
        time.sleep(2) # Give it a second to bind ZMQ port

        # Start Brain Service (Execution Logic)
        print("Starting Brain Service...")
        p_brain = subprocess.Popen([sys.executable, "src/services/brain_service.py"])
        processes.append(p_brain)
        time.sleep(2)
        
        # Start Shadow Service (ML / Analytics)
        print("Starting Shadow Service...")
        p_shadow = subprocess.Popen([sys.executable, "src/services/shadow_service.py"])
        processes.append(p_shadow)
        time.sleep(1)

        # Start UI Node (Flask)
        print("Starting Web UI Node...")
        p_ui = subprocess.Popen([sys.executable, "main.py"])
        processes.append(p_ui)
        
        print("\nAll microservices started successfully.")
        print("Press Ctrl+C to stop all services.\n")

        # Wait indefinitely until interrupted
        for p in processes:
            p.wait()

    except KeyboardInterrupt:
        print("\nShutting down all microservices...")
        for p in processes:
            p.terminate()
        for p in processes:
            p.wait()
        print("Shutdown complete.")
        sys.exit(0)

if __name__ == "__main__":
    main()
