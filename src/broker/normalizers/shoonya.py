import json
from datetime import datetime
from typing import Any, List, Dict
from .base import IInstrumentNormalizer

class ShoonyaNormalizer(IInstrumentNormalizer):
    """Normalizes Shoonya CSV/Text scrip master records to universal instrument format."""
    
    def _parse_date(self, date_str: str) -> str:
        """Standardize expiry date to YYYY-MM-DD format."""
        if not date_str or date_str.strip() == "":
            return ""
        # Shoonya formats: '26-JUL-2026', '26-Jul-2026', '2026-07-26'
        for fmt in ('%d-%b-%Y', '%d-%B-%Y', '%Y-%m-%d', '%d%b%Y'):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                pass
        return date_str

    def normalize(self, raw_data: Any) -> List[Dict[str, Any]]:
        """Expects raw_data to be a list of dicts (parsed from CSV/Text)."""
        if not isinstance(raw_data, list):
            raise ValueError("Shoonya raw data must be a list of dictionaries.")
            
        normalized = []
        for entry in raw_data:
            try:
                # Shoonya standard columns: Exchange, Token, Symbol, TradingSymbol, Expiry, OptionType, StrikePrice, LotSize, TickSize, Instrument
                token = str(entry.get("Token", entry.get("token", ""))).strip()
                if not token:
                    continue
                    
                exch_seg = str(entry.get("Exchange", entry.get("exchange", ""))).strip().upper()
                name = str(entry.get("Symbol", entry.get("symbol", ""))).strip().upper()
                broker_symbol = str(entry.get("TradingSymbol", entry.get("trading_symbol", ""))).strip()
                instrumenttype = str(entry.get("Instrument", entry.get("instrument_type", ""))).strip().upper()
                
                # OptionType and Expiry
                expiry = self._parse_date(entry.get("Expiry", entry.get("expiry", "")))
                
                try:
                    strike = float(entry.get("StrikePrice", entry.get("strike_price", 0.0)))
                except (ValueError, TypeError):
                    strike = 0.0
                    
                try:
                    lotsize = int(entry.get("LotSize", entry.get("lot_size", 1)))
                except (ValueError, TypeError):
                    lotsize = 1
                    
                try:
                    tick_size = float(entry.get("TickSize", entry.get("tick_size", 0.05)))
                except (ValueError, TypeError):
                    tick_size = 0.05

                # Standardize Index Names
                univ_name = name
                if name == "NIFTY" and (instrumenttype == "INDEX" or token == "26000"):
                    univ_name = "NIFTY_50"

                # Generate Universal Symbol
                if exch_seg in ["NSE", "BSE"]:
                    symbol = f"{exch_seg}:{univ_name}"
                elif exch_seg in ["NFO", "BFO"]:
                    if "FUT" in instrumenttype:
                        symbol = f"{exch_seg}:{univ_name}:{expiry}:FUT"
                    elif "OPT" in instrumenttype:
                        opt_type = str(entry.get("OptionType", "")).upper()
                        if not opt_type:
                            opt_type = "CE" if broker_symbol.upper().endswith("CE") else "PE" if broker_symbol.upper().endswith("PE") else "XX"
                        symbol = f"{exch_seg}:{univ_name}:{expiry}:{int(strike)}:{opt_type}"
                    else:
                        symbol = f"{exch_seg}:{broker_symbol.upper()}"
                else:
                    symbol = f"{exch_seg}:{broker_symbol.upper()}"

                # Metadata JSON
                metadata = {
                    "raw_symbol": broker_symbol
                }
                
                # Format expiry to DD-MMM-YYYY for compatibility if present
                exp_raw = entry.get("Expiry", "")
                if expiry and not exp_raw:
                    try:
                        dt = datetime.strptime(expiry, '%Y-%m-%d')
                        exp_raw = dt.strftime('%d%b%Y').upper()
                    except ValueError:
                        pass
                
                normalized.append({
                    "symbol": symbol.upper(),
                    "name": univ_name.upper(),
                    "exch_seg": exch_seg,
                    "expiry": exp_raw,
                    "strike": strike,
                    "lotsize": lotsize,
                    "instrumenttype": instrumenttype,
                    "tick_size": tick_size,
                    "description": broker_symbol,
                    "metadata_json": json.dumps(metadata),
                    "broker_name": "SHOONYA",
                    "broker_token": token,
                    "broker_symbol": broker_symbol,
                    "last_updated": datetime.utcnow().isoformat()
                })
            except Exception:
                pass
                
        return normalized
