import os
import json
import hashlib
import uuid
import requests
from datetime import datetime
from typing import List, Dict, Any, Tuple
from src.core.instrument_repository import InstrumentRepository
from src.broker.normalizers.angel_one import AngelOneNormalizer
from src.broker.normalizers.shoonya import ShoonyaNormalizer
from src.config.engineering_config import DATA_DIR
from src.utils.logger import get_logger

logger = get_logger("instrument_sync_service")

ANGEL_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
CACHE_FILE = os.path.join(DATA_DIR, "OpenAPIScripMaster.json")

class InstrumentSyncService:
    """Sole authority responsible for downloading, validating, normalizing, and storing instrument metadata."""

    def __init__(self):
        self.repo = InstrumentRepository()
        self.angel_normalizer = AngelOneNormalizer()
        self.shoonya_normalizer = ShoonyaNormalizer()

    def _compute_hash(self, content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    def sync_angel(self, force: bool = False) -> Tuple[bool, str]:
        """Download, hash-check, and sync Angel One instruments."""
        logger.info("Starting Angel One instrument synchronization...")
        try:
            # Download/Fetch master content
            response = requests.get(ANGEL_URL, timeout=30)
            if response.status_code != 200:
                logger.error(f"Failed to fetch Angel One master. Status: {response.status_code}")
                return False, "Fetch failed"
                
            content = response.content
            current_hash = self._compute_hash(content)
            
            # Check last sync hash
            last_hash = self.repo.get_sync_hash("ANGEL")
            if current_hash == last_hash and not force:
                logger.info("Angel One master file is unchanged (hashes match). Skipping sync.")
                return True, "Unchanged"
                
            # Cache the file locally for safety
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            with open(CACHE_FILE, "wb") as f:
                f.write(content)

            # Parse and normalize
            raw_data = json.loads(content.decode("utf-8"))
            normalized_instruments = self.angel_normalizer.normalize(raw_data)
            
            # Prepare mappings
            mappings = []
            for inst in normalized_instruments:
                mappings.append({
                    "symbol": inst["symbol"],
                    "broker_name": "ANGEL",
                    "broker_token": inst["broker_token"],
                    "broker_symbol": inst["broker_symbol"],
                    "last_updated": inst["last_updated"]
                })

            # Record sync details
            sync_record = {
                "sync_id": str(uuid.uuid4()),
                "broker_name": "ANGEL",
                "master_version": datetime.utcnow().strftime("%Y%m%d"),
                "source_hash": current_hash,
                "sync_timestamp": datetime.utcnow().isoformat(),
                "records_added": len(normalized_instruments),
                "records_updated": 0
            }

            self.repo.stage_and_swap_instruments("ANGEL", normalized_instruments, mappings, sync_record)
            logger.info("Angel One synchronization completed successfully.")
            return True, "Synced"
        except Exception as e:
            logger.error(f"Error syncing Angel One instruments: {e}")
            return False, str(e)

    def sync_shoonya(self, force: bool = False) -> Tuple[bool, str]:
        """Mock/sync Shoonya instruments since SDK is not yet integrated."""
        logger.info("Starting Shoonya instrument synchronization...")
        try:
            # We mock the Shoonya master file structure
            mock_records = [
                {"Exchange": "NSE", "Token": "22", "Symbol": "ACC", "TradingSymbol": "ACC-EQ", "LotSize": "1", "Instrument": "EQUITY", "TickSize": "0.05"},
                {"Exchange": "NSE", "Token": "1594", "Symbol": "INFY", "TradingSymbol": "INFY-EQ", "LotSize": "1", "Instrument": "EQUITY", "TickSize": "0.05"},
                {"Exchange": "NSE", "Token": "26000", "Symbol": "NIFTY", "TradingSymbol": "Nifty 50", "LotSize": "1", "Instrument": "INDEX", "TickSize": "0.05"},
                {"Exchange": "NFO", "Token": "35001", "Symbol": "NIFTY", "TradingSymbol": "NIFTY26JUL26FUT", "LotSize": "75", "Expiry": "26-JUL-2026", "Instrument": "FUTIDX", "TickSize": "0.05"},
                {"Exchange": "NFO", "Token": "35002", "Symbol": "NIFTY", "TradingSymbol": "NIFTY26JUL2624000CE", "LotSize": "75", "Expiry": "26-JUL-2026", "StrikePrice": "24000", "OptionType": "CE", "Instrument": "OPTIDX", "TickSize": "0.05"}
            ]
            
            content_bytes = json.dumps(mock_records).encode("utf-8")
            current_hash = self._compute_hash(content_bytes)
            
            last_hash = self.repo.get_sync_hash("SHOONYA")
            if current_hash == last_hash and not force:
                logger.info("Shoonya master file is unchanged. Skipping sync.")
                return True, "Unchanged"
                
            normalized_instruments = self.shoonya_normalizer.normalize(mock_records)
            
            mappings = []
            for inst in normalized_instruments:
                mappings.append({
                    "symbol": inst["symbol"],
                    "broker_name": "SHOONYA",
                    "broker_token": inst["broker_token"],
                    "broker_symbol": inst["broker_symbol"],
                    "last_updated": inst["last_updated"]
                })

            sync_record = {
                "sync_id": str(uuid.uuid4()),
                "broker_name": "SHOONYA",
                "master_version": datetime.utcnow().strftime("%Y%m%d"),
                "source_hash": current_hash,
                "sync_timestamp": datetime.utcnow().isoformat(),
                "records_added": len(normalized_instruments),
                "records_updated": 0
            }

            self.repo.stage_and_swap_instruments("SHOONYA", normalized_instruments, mappings, sync_record)
            logger.info("Shoonya synchronization completed successfully.")
            return True, "Synced"
        except Exception as e:
            logger.error(f"Error syncing Shoonya instruments: {e}")
            return False, str(e)

    def run_sync_all(self, force: bool = False) -> None:
        """Run synchronization for all active brokers."""
        logger.info("=== STARTING FULL INSTRUMENT REGISTRY SYNCHRONIZATION ===")
        
        # Sync Angel One
        self.sync_angel(force=force)
        
        # Sync Shoonya
        self.sync_shoonya(force=force)
        
        logger.info("=== INSTRUMENT REGISTRY SYNCHRONIZATION COMPLETED ===")

def run_sync(force: bool = False) -> None:
    service = InstrumentSyncService()
    service.run_sync_all(force=force)

if __name__ == "__main__":
    run_sync(force=True)
