import logging
from typing import Optional
from src.execution.trade_context import TradeLeg

logger = logging.getLogger("order_lifecycle")

class OrderLifecycle:
    """
    Abstract Base Class for managing the lifecycle of an order.
    It encapsulates the logic of entering and exiting positions, handling
    pending orders, and applying broker-specific rules (like modify vs cancel+new).
    """

    def execute_entry(self, leg: TradeLeg) -> bool:
        """
        Executes the entry order for a TradeLeg.
        Returns True if successful, False otherwise.
        """
        raise NotImplementedError

    def execute_exit(self, leg: TradeLeg, reason: str, exit_price: Optional[float] = None) -> bool:
        """
        Executes the market exit for a TradeLeg.
        It must handle pending limit orders according to broker-specific rules.
        Returns True if successful, False otherwise.
        """
        raise NotImplementedError


class PaperOrderLifecycle(OrderLifecycle):
    """
    Simulates instantaneous order execution for paper trading.
    """
    import uuid

    def execute_entry(self, leg: TradeLeg) -> bool:
        leg.status = "OPEN"
        leg.paper_order_id = f"PAPER_{self.uuid.uuid4().hex[:8].upper()}"
        logger.info(f"[PaperOrderLifecycle] Entry executed for leg {leg.leg_id}. Paper Order ID: {leg.paper_order_id}")
        return True

    def execute_exit(self, leg: TradeLeg, reason: str, exit_price: Optional[float] = None) -> bool:
        if leg.status != "OPEN":
            logger.warning(f"[PaperOrderLifecycle] Attempted to exit leg {leg.leg_id} which is not OPEN.")
            return False
            
        leg.close_leg(exit_price or leg.current_price, reason)
        logger.info(f"[PaperOrderLifecycle] Exit executed for leg {leg.leg_id} at {leg.exit_price}. Reason: {reason}")
        return True
