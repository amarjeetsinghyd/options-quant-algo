"""BrokerPolicy – lightweight configuration for broker usage.

The *policy* model captures simple operational rules that can be consulted by
services without being as heavyweight as the full :class:`BrokerManifest`.
It is intentionally minimal and can be extended in later phases (e.g.,
Phase 1.1) when more sophisticated policy handling is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class BrokerPolicy:
    """Lightweight policy governing broker interactions.

    Attributes
    ----------
    max_retries: int
        Maximum number of automatic retries for transient failures.
    backoff_factor: float
        Multiplier for exponential back‑off (e.g., ``0.5`` → 0.5s, 1s, 2s …).
    allowed_operations: Tuple[str, ...]
        Whitelisted operation names (e.g., ``"place_order"``, ``"fetch_data"``).
    """

    max_retries: int = 3
    backoff_factor: float = 0.5
    allowed_operations: Tuple[str, ...] = ("place_order", "cancel_order", "fetch_market_data", "fetch_historical")
