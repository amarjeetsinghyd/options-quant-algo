# C:\Quant\src\core\market_data_cache.py
# QOT v1.0.0 — Unified thread-safe MarketDataCache storing InstrumentState

import time
import threading
from dataclasses import dataclass

@dataclass
class InstrumentState:
    token: str
    symbol: str
    exchange: str
    ltp: float = 0.0
    bid: float = 0.0
    ask: float = 0.0
    spread: float = 0.0
    volume: int = 0
    last_tick_time: float = 0.0  # Unix timestamp
    sequence: int = 0
    latency: int = 0
    tick_direction: str = "NEUTRAL"
    
    @property
    def age_ms(self) -> float:
        """Calculates data freshness age in milliseconds."""
        if self.last_tick_time == 0.0:
            return 999999.0
        return max(0.0, (time.time() - self.last_tick_time) * 1000.0)

class MarketDataCache:
    """Thread-safe cache holding InstrumentState for Nifty and active option chain."""
    def __init__(self):
        self._states = {}
        self._lock = threading.Lock()
        
    def update_tick(self, token: str, symbol: str, exchange: str, ltp: float, bid: float = 0.0, ask: float = 0.0, volume: int = 0, seq: int = 0, latency: int = 0, direction: str = "NEUTRAL") -> None:
        with self._lock:
            if token not in self._states:
                self._states[token] = InstrumentState(token=token, symbol=symbol, exchange=exchange)
            
            state = self._states[token]
            state.ltp = ltp
            if bid > 0.0: state.bid = bid
            if ask > 0.0: state.ask = ask
            if bid > 0.0 and ask > 0.0: state.spread = round(ask - bid, 2)
            if volume > 0: state.volume = volume
            state.sequence = seq
            state.latency = latency
            state.tick_direction = direction
            state.last_tick_time = time.time()
            
    def get_state(self, token: str) -> InstrumentState:
        with self._lock:
            return self._states.get(token)

    def get_ltp(self, token: str, default: float = 0.0) -> float:
        with self._lock:
            state = self._states.get(token)
            return state.ltp if state else default
            
    def get_all_states(self) -> dict:
        with self._lock:
            # Return copies to prevent mutability race conditions
            return {t: InstrumentState(
                token=s.token, symbol=s.symbol, exchange=s.exchange,
                ltp=s.ltp, bid=s.bid, ask=s.ask, spread=s.spread,
                volume=s.volume, last_tick_time=s.last_tick_time,
                sequence=s.sequence, latency=s.latency, tick_direction=s.tick_direction
            ) for t, s in self._states.items()}
