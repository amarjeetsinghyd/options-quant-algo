"""Generic broker validation runner.

The ``run_broker_validation`` function is broker‑neutral. It reads the ``BROKER``
environment variable, locates the appropriate validator script via the factory,
executes it, and returns a structured dictionary containing the overall status and
per‑step details.  The result is suitable for programmatic consumption by the
engine bootstrap (e.g., ``start_all.py``).
"""

import os
import sys
import json
import subprocess
import logging
from typing import Dict, Any

from .validator_factory import get_validator_path

# Load .env so that BROKER and other env vars are available even when PM2
# does not forward them from the parent shell environment.
try:
    from dotenv import load_dotenv as _load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), ".env")
    _load_dotenv(dotenv_path=_env_path)
except Exception:
    pass  # dotenv is optional; env vars may already be set

logger = logging.getLogger("broker_validation")


def _execute_script(script_path: str) -> Dict[str, Any]:
    """Execute *script_path* and parse the final JSON line.

    The validation scripts are expected to emit a JSON object on the last line
    of stdout.  Any preceding human‑readable lines are ignored.
    """
    try:
        result = subprocess.run(
            [sys.executable, script_path],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            timeout=300,
        )
    except Exception as exc:
        logger.exception("Failed to run validator script %s", script_path)
        return {"broker": os.getenv("BROKER", "UNKNOWN"), "status": "FAIL", "details": {"error": str(exc)}}

    if result.returncode != 0:
        logger.error("Validator script %s exited with code %d", script_path, result.returncode)

    # The script may print many lines; the last non‑empty line should be JSON.
    lines = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    if not lines:
        logger.error("Validator script produced no output: %s", script_path)
        return {"broker": os.getenv("BROKER", "UNKNOWN"), "status": "FAIL", "details": {"error": "no output"}}

    json_line = lines[-1]
    try:
        return json.loads(json_line)
    except json.JSONDecodeError:
        logger.error("Last line of validator output is not valid JSON: %s", json_line)
        return {"broker": os.getenv("BROKER", "UNKNOWN"), "status": "FAIL", "details": {"error": "invalid json"}}


def run_broker_validation() -> Dict[str, Any]:
    """Run the appropriate broker validation and return a structured result.

    Reads BROKER from environment (or .env file). If BROKER is not set,
    validation is skipped and treated as a PASS to avoid blocking startup.
    For ANGEL broker, validation is skipped (no external validator needed).
    """
    broker = os.getenv("BROKER", "").upper()
    if not broker:
        logger.warning("BROKER env var not set. Skipping broker validation (treated as PASS).")
        return {"broker": "UNSET", "status": "PASS", "details": {"note": "BROKER not configured"}}
    if broker == "ANGEL":
        logger.info("Broker %s selected – skipping validation.", broker)
        return {"broker": broker, "status": "PASS", "details": {}}

    script_path = get_validator_path(broker)
    if not script_path or not os.path.isfile(script_path):
        logger.warning(
            "No validator script found for broker %s (expected %s). "
            "Skipping pre-flight validation — session auth will validate on startup.",
            broker, script_path
        )
        return {"broker": broker, "status": "PASS", "details": {"note": "no validator script, skipped"}}

    logger.info("Running broker validation script for %s: %s", broker, script_path)
    return _execute_script(script_path)
