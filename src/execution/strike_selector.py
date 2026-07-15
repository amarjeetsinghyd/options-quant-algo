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
        otm_strikes = StrikeSelector.get_otm_strikes(atm_strike, signal_type, index_name, max_depth=20)
        
        remaining_funds = available_funds
        
        # Step 1: Gather valid options and their costs
        valid_opts = []
        for target_strike in otm_strikes:
            strike_angel = int(target_strike * 100)
            strike_shoonya = int(target_strike)
            opts_strike_int = opts['strike'].astype(float).astype(int)
            match = opts[(opts_strike_int == strike_angel) | (opts_strike_int == strike_shoonya)]
            
            if match.empty:
                continue
                
            opt_row = match.iloc[0]
            token = str(opt_row['token'])
            ltp = option_cache.get(token) or option_cache.get(int(token)) if token.isdigit() else None
            
            if ltp is not None and ltp > 0:
                valid_opts.append((opt_row, ltp, ltp * lot_size))

        if not valid_opts:
            return []

        # Step 2: Find the FIRST affordable OTM strike
        start_idx = -1
        for i, (opt_row, ltp, cost_per_lot) in enumerate(valid_opts):
            if cost_per_lot <= remaining_funds:
                start_idx = i
                break
                
        if start_idx == -1:
            logger.warning(f"[StrikeSelector] No affordable OTM strikes found for funds: {available_funds}")
            return []

        # Step 3: Forward Ladder (up to 5 OTMs)
        allocations_dict = {}
        ladder_end_idx = min(start_idx + 5, len(valid_opts))
        
        for i in range(start_idx, ladder_end_idx):
            opt_row, ltp, cost_per_lot = valid_opts[i]
            if remaining_funds >= cost_per_lot:
                allocations_dict[i] = allocations_dict.get(i, 0) + 1
                remaining_funds -= cost_per_lot
            else:
                # If we cannot afford the immediate next consecutive OTM, we halt the forward ladder.
                break

        # Step 4: Reverse Sweep (looping back from the furthest reached OTM down to the 1st)
        if allocations_dict:
            max_idx = max(allocations_dict.keys())
            while True:
                allocated_in_sweep = False
                for i in range(max_idx, start_idx - 1, -1):
                    opt_row, ltp, cost_per_lot = valid_opts[i]
                    if remaining_funds >= cost_per_lot:
                        allocations_dict[i] += 1
                        remaining_funds -= cost_per_lot
                        allocated_in_sweep = True
                
                # If we couldn't afford ANY lots during the entire reverse pass, we are done
                if not allocated_in_sweep:
                    break
                    
        # Step 5: Format output
        final_allocations = []
        # Return allocations ordered from ITM-most to OTM-most
        for i in sorted(allocations_dict.keys()):
            qty = allocations_dict[i]
            if qty > 0:
                opt_row, ltp, cost_per_lot = valid_opts[i]
                final_allocations.append((opt_row, qty, ltp))
                logger.info(f"[StrikeSelector] Selected {qty} lot(s) of {opt_row['symbol']} at {ltp} (Total Cost: {qty * cost_per_lot:.2f}).")
                
        logger.info(f"[StrikeSelector] Pyramiding complete. Remaining funds: {remaining_funds:.2f}")
        return final_allocations
