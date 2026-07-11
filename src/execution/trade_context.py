from typing import List, Dict, Any
from datetime import datetime
import uuid

class TradeLeg:
    def __init__(self, token: str, symbol: str, strike: float, option_type: str, quantity: int, entry_price: float, broker_order_id: str = None, paper_order_id: str = None):
        self.leg_id = str(uuid.uuid4())
        self.token = token
        self.symbol = symbol
        self.strike = strike
        self.option_type = option_type
        self.quantity = quantity
        self.entry_price = entry_price
        self.current_price = entry_price
        self.broker_order_id = broker_order_id
        self.paper_order_id = paper_order_id
        self.status = "OPEN" # OPEN, CLOSED, REJECTED, PENDING_EXIT
        self.entry_time = datetime.now()
        self.exit_time = None
        self.exit_price = None
        self.exit_reason = None
        self.pnl = 0.0

    def close_leg(self, exit_price: float, reason: str):
        self.status = "CLOSED"
        self.exit_time = datetime.now()
        self.exit_price = exit_price
        self.exit_reason = reason
        self.pnl = (self.exit_price - self.entry_price) * self.quantity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "leg_id": self.leg_id,
            "token": self.token,
            "symbol": self.symbol,
            "strike": self.strike,
            "option_type": self.option_type,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "broker_order_id": self.broker_order_id,
            "paper_order_id": self.paper_order_id,
            "status": self.status,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_price": self.exit_price,
            "exit_reason": self.exit_reason,
            "pnl": self.pnl
        }


class TradeContext:
    def __init__(self, signal_type: str, strategy: str, index_entry: float, decision_payload: Dict[str, Any] = None):
        self.context_id = str(uuid.uuid4())
        self.signal_type = signal_type
        self.strategy = strategy
        self.index_entry = index_entry
        self.decision_payload = decision_payload
        self.legs: List[TradeLeg] = []
        self.status = "OPEN" # OPEN, CLOSED
        self.entry_time = datetime.now()
        self.exit_time = None
        self.total_pnl = 0.0

    def add_leg(self, leg: TradeLeg):
        self.legs.append(leg)

    def close_context(self):
        self.status = "CLOSED"
        self.exit_time = datetime.now()
        self.total_pnl = sum(leg.pnl for leg in self.legs if leg.status == "CLOSED")

    def all_legs_closed(self) -> bool:
        return all(leg.status in ["CLOSED", "REJECTED"] for leg in self.legs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_id": self.context_id,
            "signal_type": self.signal_type,
            "strategy": self.strategy,
            "index_entry": self.index_entry,
            "status": self.status,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "total_pnl": self.total_pnl,
            "decision_payload": self.decision_payload,
            "legs": [leg.to_dict() for leg in self.legs]
        }
