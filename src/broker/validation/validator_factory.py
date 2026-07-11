"""Factory for locating broker‑specific validation scripts.

The function ``get_validator_path`` returns an absolute path to the validation
script associated with the supplied broker name.  The mapping can be extended
as new brokers are supported.
"""

import os
from typing import Optional

# Base directory of the repository – used to build absolute paths.
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# Mapping of broker identifiers to their validation script relative paths.
# Paths are stored relative to the repository root for portability.
BROKER_VALIDATORS = {
    "SHOONYA": os.path.join(_REPO_ROOT, "standalone_shoonya_validation.py"),
    # Future brokers can be added here, e.g. "ANGEL": "path/to/angel_validation.py"
}


def get_validator_path(broker_name: str) -> Optional[str]:
    """Return the absolute path to the validator script for *broker_name*.

    The lookup is case‑insensitive. If no validator is registered, ``None`` is
    returned.
    """
    if not broker_name:
        return None
    path = BROKER_VALIDATORS.get(broker_name.upper())
    return path
