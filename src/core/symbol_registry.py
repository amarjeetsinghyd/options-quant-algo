import os
import json
from src.config.engineering_config import DATA_DIR
from src.utils.logger import get_logger

logger = get_logger("symbol_registry")

class SymbolRegistry:
    """
    Broker-Agnostic Symbol Mapper.
    Loads the broker's token dictionary into memory for O(1) lookups.
    Translates any broker-specific token (e.g. '26000') to a universal symbol (e.g. 'Nifty 50').
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SymbolRegistry, cls).__new__(cls)
            cls._instance._init_registry()
        return cls._instance

    def _init_registry(self):
        self.token_to_symbol = {}
        self.symbol_to_token = {}
        
        master_file = os.path.join(DATA_DIR, "OpenAPIScripMaster.json")
        if not os.path.exists(master_file):
            logger.error(f"ScripMaster not found at {master_file}. Symbol lookup will fallback to raw tokens.")
            return

        try:
            logger.info("Loading Broker Symbol Registry into memory...")
            with open(master_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            for item in data:
                token = str(item.get('token', ''))
                symbol = str(item.get('symbol', '')).upper()
                
                # Normalize common index symbols for universal ML compatibility
                if token == "26000": symbol = "NIFTY_50"
                if token == "26009": symbol = "BANKNIFTY"
                if token == "99919000": symbol = "SENSEX"
                
                if token and symbol:
                    self.token_to_symbol[token] = symbol
                    self.symbol_to_token[symbol] = token
                    
            logger.info(f"Loaded {len(self.token_to_symbol)} universal symbols in O(1) registry.")
        except Exception as e:
            logger.error(f"Failed to load Symbol Registry: {e}")

    def get_symbol(self, token: str, fallback_symbol: str = "") -> str:
        """Translates a broker token to a universal symbol in O(1) time."""
        token = str(token)
        if token in self.token_to_symbol:
            return self.token_to_symbol[token]
        # If we couldn't find it, use the fallback symbol provided by the live feed
        if fallback_symbol:
            return fallback_symbol.upper()
        # Absolute fallback: just return the token
        return token
