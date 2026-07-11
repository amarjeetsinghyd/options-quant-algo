"""Normalized broker data models.

All adapters must convert their native SDK objects to these models so that
the rest of the codebase works with a broker‑agnostic representation.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

@dataclass
class BrokerInstrument:
    symbol: str
    exchange: Optional[str] = None
    instrument_type: Optional[str] = None

@dataclass
class BrokerTick:
    instrument: BrokerInstrument
    price: float
    timestamp: datetime
    volume: Optional[int] = None

@dataclass
class BrokerOrder:
    order_id: str
    instrument: BrokerInstrument
    side: str  # "BUY" or "SELL"
    quantity: int
    price: Optional[float] = None
    status: Optional[str] = None
    timestamp: datetime = datetime.utcnow()

@dataclass
class BrokerPosition:
    instrument: BrokerInstrument
    quantity: int
    avg_price: float

@dataclass
class BrokerSession:
    token: str
    expiry: datetime

@dataclass
class BrokerResponse:
    success: bool
    data: Optional[any] = None
    error: Optional[Exception] = None
