from abc import ABC, abstractmethod
from typing import Any, List, Dict

class IInstrumentNormalizer(ABC):
    """Abstract interface for normalising raw broker scrip master data to universal formats."""
    
    @abstractmethod
    def normalize(self, raw_data: Any) -> List[Dict[str, Any]]:
        """Normalize raw master records.
        
        Returns a list of dictionaries matching the schema for instruments:
        {
            'symbol': str,            # Universal Symbol, e.g. "NSE:INFY", "NFO:NIFTY26JUL2612000CE"
            'name': str,              # Root ticker, e.g. "INFY", "NIFTY"
            'exch_seg': str,          # Segment, e.g. "NSE", "NFO", "BSE"
            'expiry': str,            # Expiry date string, e.g. "26JUL2026"
            'strike': float,          # Strike price
            'lotsize': int,           # Lot size
            'instrumenttype': str,    # e.g. "EQUITY", "FUTIDX", "OPTIDX"
            'tick_size': float,       # Tick size
            'description': str,       # Description
            'broker_token': str,      # Broker-specific token
            'broker_symbol': str,     # Broker-specific symbol
            'metadata_json': str,     # Extensible JSON payload
        }
        """
        pass
