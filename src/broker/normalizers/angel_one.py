import json
from datetime import datetime
from typing import Any, List, Dict
from .base import IInstrumentNormalizer

class AngelOneNormalizer(IInstrumentNormalizer):
    """Normalizes Angel One API scrip master records to universal instrument format."""
    
    def _parse_date(self, date_str: str) -> str:
        """Standardize expiry date to YYYY-MM-DD format."""
        if not date_str or date_str.strip() == "":
            return ""
        for fmt in ('%d%b%Y', '%d-%b-%Y', '%Y-%m-%d'):
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                pass
        return date_str

    def normalize(self, raw_data: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_data, list):
            raise ValueError("Angel One raw data must be a list of dictionaries.")
            
        normalized = []
        for entry in raw_data:
            try:
                token = str(entry.get("token", "")).strip()
                if not token:
                    continue
                    
                exch_seg = str(entry.get("exch_seg", "")).strip().upper()
                name = str(entry.get("name", "")).strip().upper()
                raw_symbol = str(entry.get("symbol", "")).strip()
                instrumenttype = str(entry.get("instrumenttype", "")).strip().upper()
                
                # Expiry and Strike
                expiry = self._parse_date(entry.get("expiry", ""))
                try:
                    strike = float(entry.get("strike", 0.0))
                except (ValueError, TypeError):
                    strike = 0.0
                    
                try:
                    lotsize = int(entry.get("lotsize", 1))
                except (ValueError, TypeError):
                    lotsize = 1
                    
                try:
                    tick_size = float(entry.get("tick_size", 0.05))
                except (ValueError, TypeError):
                    tick_size = 0.05

                # Standardize index names for ML compatibility
                if name == "NIFTY" and token == "99926000":
                    univ_name = "NIFTY_50"
                elif name == "BANKNIFTY" or token == "99926009":
                    univ_name = "BANKNIFTY"
                elif name == "SENSEX" or token == "99919000":
                    univ_name = "SENSEX"
                elif name == "NIFTY" and "Nifty 50" in raw_symbol:
                    univ_name = "NIFTY_50"
                else:
                    univ_name = name

                # Generate Universal Symbol
                if exch_seg in ["NSE", "BSE"]:
                    if instrumenttype == "AMXIDX":
                        # Index (e.g. NSE:NIFTY_50)
                        symbol = f"{exch_seg}:{univ_name}"
                    else:
                        # Equity (e.g. NSE:INFY)
                        symbol = f"{exch_seg}:{univ_name}"
                elif exch_seg in ["NFO", "BFO"]:
                    if instrumenttype == "FUTIDX":
                        # Future (e.g. NFO:NIFTY:2026-07-26:FUT)
                        symbol = f"{exch_seg}:{univ_name}:{expiry}:FUT"
                    elif instrumenttype == "OPTIDX":
                        # Option (e.g. NFO:NIFTY:2026-07-26:24000:CE)
                        opt_type = "CE" if raw_symbol.upper().endswith("CE") else "PE" if raw_symbol.upper().endswith("PE") else "XX"
                        symbol = f"{exch_seg}:{univ_name}:{expiry}:{int(strike)}:{opt_type}"
                    else:
                        symbol = f"{exch_seg}:{raw_symbol.upper()}"
                else:
                    symbol = f"{exch_seg}:{raw_symbol.upper()}"

                # Metadata JSON
                metadata = {
                    "freeze_qty": entry.get("freeze_qty", "0"),
                    "raw_symbol": raw_symbol
                }
                
                normalized.append({
                    "symbol": symbol.upper(),
                    "name": univ_name.upper(),
                    "exch_seg": exch_seg,
                    "expiry": entry.get("expiry", ""),  # Keep original format for internal compatibility
                    "strike": strike,
                    "lotsize": lotsize,
                    "instrumenttype": instrumenttype,
                    "tick_size": tick_size,
                    "description": entry.get("symbol", ""),
                    "metadata_json": json.dumps(metadata),
                    "broker_name": "ANGEL",
                    "broker_token": token,
                    "broker_symbol": raw_symbol,
                    "last_updated": datetime.utcnow().isoformat()
                })
            except Exception:
                pass
                
        return normalized
