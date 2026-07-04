import os
from pathlib import Path

class ShutdownManager:
    """Manages cross-platform graceful shutdown triggers for headless processes."""
    
    def __init__(self, runtime_dir: str = "runtime"):
        self.runtime_dir = Path(os.path.abspath(runtime_dir))
        self.trigger_file = self.runtime_dir / "quant_engine.shutdown"
        
    def is_shutdown_requested(self) -> bool:
        """Check if a graceful shutdown has been requested by the presence of the trigger file."""
        return self.trigger_file.exists()
        
    def clear_shutdown_trigger(self) -> None:
        """Delete the shutdown trigger file to clear the state."""
        if self.trigger_file.exists():
            try:
                self.trigger_file.unlink()
            except Exception:
                pass
                
    def request_shutdown(self) -> None:
        """Create the trigger file to request a graceful shutdown of the engine."""
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        with open(self.trigger_file, "w", encoding="utf-8") as f:
            f.write("SHUTDOWN")
