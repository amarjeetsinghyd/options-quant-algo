import sys
import subprocess
from typing import List, Dict, Any, Optional

class ProcessLauncher:
    """Centralized utility to launch processes headlessly across platforms."""

    @staticmethod
    def spawn(command: List[str], env: Optional[Dict[str, str]] = None, 
              stdout: Any = None, stderr: Any = None, cwd: Optional[str] = None) -> subprocess.Popen:
        """Spawn a background subprocess headlessly (no visible console window on Windows)."""
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
            
        return subprocess.Popen(
            command,
            env=env,
            stdout=stdout,
            stderr=stderr,
            cwd=cwd,
            creationflags=creationflags
        )

    @staticmethod
    def run_command(command: str, shell: bool = True, capture_output: bool = True, 
                    text: bool = True) -> subprocess.CompletedProcess:
        """Execute a synchronous command line headlessly (no visible console window on Windows)."""
        creationflags = 0
        if sys.platform == "win32":
            creationflags = subprocess.CREATE_NO_WINDOW
            
        return subprocess.run(
            command,
            shell=shell,
            capture_output=capture_output,
            text=text,
            creationflags=creationflags
        )
