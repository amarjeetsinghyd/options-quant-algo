"""Broker Metrics – operational counters and aggregates.

Metrics are **pure data** that can be exported to monitoring systems or
consumed by adaptive logic.  They are deliberately separate from the runtime
state to keep concerns distinct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass()
class BrokerMetrics:
    # Latency statistics (in milliseconds)
    rest_latency_ms: List[float] = field(default_factory=list)
    websocket_latency_ms: List[float] = field(default_factory=list)

    # Order flow counters
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_rejected: int = 0
    orders_cancelled: int = 0

    # Error / health counters
    api_failures: int = 0
    rate_limit_hits: int = 0
    reconnects: int = 0
    packet_loss_events: int = 0
    last_health_score: Optional[float] = None
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def record_rest_latency(self, ms: float) -> None:
        self.rest_latency_ms.append(ms)
        self.last_updated = datetime.utcnow()

    def record_ws_latency(self, ms: float) -> None:
        self.websocket_latency_ms.append(ms)
        self.last_updated = datetime.utcnow()
