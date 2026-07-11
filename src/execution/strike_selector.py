import logging
import pandas as pd
from typing import List, Dict, Tuple

logger = logging.getLogger("strike_selector")

class StrikeSelector:
    """
    Broker-agnostic Strike Selector.
    Responsibility: Select the nearest affordable OTM strike(s) based on available funds.
    It supports multi-strike horizontal scaling without ever migrating into ITM.
    """

    @staticmethod
    def calculate_atm_strike(index_price: float, index_name: str) -> float:
        step = 100 if "SENSEX" in str(index_name).upper() else 50
        return round(index_price / step) * step

    @staticmethod
    def get_otm_strikes(atm_strike: float, signal_type: str, index_name: str, max_depth: int = 15) -> List[float]:
        """
        Returns a list of strikes starting from ATM and moving progressively OTM.
        """
        step = 100 if "SENSEX" in str(index_name).upper() else 50
        strikes = []
        for i in range(max_depth):
            if signal_type == "CALL":
                strikes.append(atm_strike + (i * step))
            else:
                strikes.append(atm_strike - (i * step))
        return strikes

    @staticmethod
    def select_strikes(
        signal_type: str,
        index_price: float,
        index_name: str,
        weekly_opts: pd.DataFrame,
        option_cache: Dict[str, float],
        available_funds: float,
        lot_size: int,
    ) -> List[Tuple[pd.Series, int, float]]:
        """
        Selects strikes based on Available Funds -> Nearest Affordable OTM.
        Scales horizontally across OTM strikes if funds permit.
        Returns a list of tuples: [(opt_row, quantity, ltp)]
        """
        if weekly_opts.empty:
            logger.debug("[StrikeSelector] Option chain is empty. Aborting selection.")
            return []

        opt_type = "CE" if signal_type == "CALL" else "PE"
        opts = weekly_opts[weekly_opts['symbol'].str.endswith(opt_type)]
        
        atm_strike = StrikeSelector.calculate_atm_strike(index_price, index_name)
        otm_strikes = StrikeSelector.get_otm_strikes(atm_strike, signal_type, index_name)
        
        remaining_funds = available_funds
        allocations = []

        for target_strike in otm_strikes:
            if remaining_funds <= 0:
                break
                
            # Angel One stores strike as strike * 100
            strike_scaled = int(target_strike * 100)
            match = opts[opts['strike'].astype(float).astype(int) == strike_scaled]
            
            if match.empty:
                continue
                
            opt_row = match.iloc[0]
            token = str(opt_row['token'])
            
            # option_cache might store keys as str or int depending on adapter
            ltp = option_cache.get(token) or option_cache.get(int(token)) if token.isdigit() else None
            
            if ltp is None:
                continue
                
            cost_per_lot = ltp * lot_size
            
            if cost_per_lot <= remaining_funds:
                # Buy 1 lot of the nearest affordable OTM
                allocations.append((opt_row, 1, ltp))
                remaining_funds -= cost_per_lot
                logger.info(f"[StrikeSelector] Selected {opt_row['symbol']} at {ltp} (Cost: {cost_per_lot:.2f}). Remaining funds: {remaining_funds:.2f}")
        
        if not allocations:
            logger.warning(f"[StrikeSelector] No affordable OTM strikes found for funds: {available_funds}")
            
        return allocations
