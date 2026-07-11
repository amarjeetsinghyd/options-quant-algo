"""Broker Runtime – mutable state that changes during execution.

Unlike :class:`BrokerManifest`, the runtime model captures information that
varies while the application is running (session expiry, websocket health,
current latency, etc.).  It is deliberately **mutable** so that the broker
adapter or a health‑monitoring component can update it in‑place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional


@dataclass(slots=True)
class BrokerRuntime:
    # Session information
    session_active: bool = False
    session_expiry: Optional[datetime] = None

    # WebSocket health
    websocket_connected: bool = False
    websocket_last_heartbeat: Optional[datetime] = None
    websocket_latency_ms: Optional[float] = None
    reconnect_count: int = 0

    # Rate‑limit usage (simple counters – adapters can increment)
    rest_requests_made: int = 0
    order_requests_made: int = 0
    historical_requests_made: int = 0
    window_start: datetime = field(default_factory=datetime.utcnow)

    # Miscellaneous dynamic flags
    broker_status: str = "UNKNOWN"  # e.g. "HEALTHY", "DEGRADED", "DOWN"

    def reset_window(self) -> None:
        """Reset the rolling window used for rate‑limit accounting."""
        self.window_start = datetime.utcnow()
        self.rest_requests_made = 0
        self.order_requests_made = 0
        self.historical_requests_made = 0
