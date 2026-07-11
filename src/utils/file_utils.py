# src/utils/file_utils.py
# Atomic JSON writing utilities (stable baseline)

import os
import json
import tempfile
from datetime import datetime
from src.utils.logger import get_logger
from src.utils.provenance import get_provenance_metadata

logger = get_logger("file_utils")

def write_json_atomic(file_path: str, data: dict) -> None:
    """Write a dictionary to a JSON file atomically.
    Ensures the target directory exists, writes to a temporary file, flushes
    and fsyncs the data, then atomically replaces the target.
    """
    dir_name = os.path.dirname(file_path)
    if dir_name and not os.path.exists(dir_name):
        os.makedirs(dir_name, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(suffix=".tmp", dir=dir_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, file_path)
    except Exception:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        raise

def write_envelope_json_atomic(file_path: str, payload: dict) -> None:
    """Wrap payload in a versioned envelope and write atomically.
    The envelope includes schema version, generation timestamp, engine version,
    and git commit metadata.
    """
    try:
        prov = get_provenance_metadata()
    except Exception:
        prov = {"git_commit": "UNKNOWN"}

    envelope = {
        "schema_version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "engine_version": "1.0.0",
        "git_commit": prov.get("git_commit", "UNKNOWN"),
        "payload": payload,
    }
    write_json_atomic(file_path, envelope)
