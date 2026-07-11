from functools import lru_cache
from typing import Optional
from src.config.engineering_config import BROKER, SYMBOL_REGISTRY_CACHE_SIZE
from src.core.instrument_repository import InstrumentRepository
from src.utils.logger import get_logger

logger = get_logger("symbol_registry")

class SymbolRegistry:
    """
    Broker-Agnostic Symbol Mapper.
    Uses InstrumentRepository and an in-memory LRU cache for O(1) lookups.
    Translates any broker-specific token (e.g. '26000') to a universal symbol (e.g. 'NIFTY_50').
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SymbolRegistry, cls).__new__(cls)
            cls._instance._init_registry()
        return cls._instance

    def _init_registry(self):
        self.repo = InstrumentRepository()
        self.broker_name = BROKER.upper()
        logger.info(f"Initialized Database-Backed Symbol Registry for broker: {self.broker_name}")
        
        # Define the LRU cache dynamically based on config size
        @lru_cache(maxsize=SYMBOL_REGISTRY_CACHE_SIZE)
        def _cached_lookup(token: str) -> Optional[str]:
            instrument = self.repo.get_instrument_by_token(self.broker_name, token)
            if instrument:
                return instrument['symbol']
            return None
            
        self._cached_lookup = _cached_lookup

    def get_symbol(self, token: str, fallback_symbol: str = "") -> str:
        """Translates a broker token to a universal symbol in O(1) time using LRU cache."""
        token = str(token).strip()
        if not token:
            return fallback_symbol.upper() if fallback_symbol else ""

        # Normalize common index symbols for universal ML compatibility (legacy fallbacks)
        if token == "26000": return "NIFTY_50"
        if token == "26009": return "BANKNIFTY"
        if token == "99919000": return "SENSEX"

        symbol = self._cached_lookup(token)
        if symbol:
            return symbol

        # If we couldn't find it, use the fallback symbol provided by the live feed
        if fallback_symbol:
            return fallback_symbol.upper()
        # Absolute fallback: just return the token
        return token

    def clear_cache(self):
        """Helper to clear the LRU cache (useful during testing/sync)."""
        self._cached_lookup.cache_clear()
