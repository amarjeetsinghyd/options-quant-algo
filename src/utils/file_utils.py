import os
import json
import tempfile
from src.utils.logger import get_logger

logger = get_logger("file_utils")

def write_json_atomic(file_path: str, data: dict) -> None:
    """Writes a dictionary as JSON atomically to prevent corruption during concurrent reads."""
    dir_name = os.path.dirname(file_path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)
        
    # Create temp file in same directory to guarantee atomic rename across partition bounds
    fd, temp_path = tempfile.mkstemp(suffix=".tmp", dir=dir_name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        # Atomically replace
        os.replace(temp_path, file_path)
    except Exception as e:
        logger.error(f"Failed to write JSON atomically to {file_path}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise e
