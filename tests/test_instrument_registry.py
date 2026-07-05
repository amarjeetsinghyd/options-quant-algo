import os
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from src.core.instrument_repository import InstrumentRepository, DB_PATH
from src.core.symbol_registry import SymbolRegistry
from src.broker.normalizers.angel_one import AngelOneNormalizer
from src.broker.normalizers.shoonya import ShoonyaNormalizer
from src.services.instrument_sync_service import InstrumentSyncService
import src.broker.instrument_registry as broker_registry

@pytest.fixture(autouse=True)
def setup_test_db():
    """Ensure database is clean before each test."""
    repo = InstrumentRepository()
    with repo._get_connection() as conn:
        repo._recreate_tables(conn)
    yield repo
    # Clean up again
    if os.path.exists(DB_PATH):
        try:
            os.remove(DB_PATH)
        except PermissionError:
            pass

def test_database_initialization(setup_test_db):
    repo = setup_test_db
    assert repo.get_count() == 0
    
    # Verify tables exist
    with repo._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row['name'] for row in cursor.fetchall()]
        assert "instruments" in tables
        assert "broker_mappings" in tables
        assert "sync_metadata" in tables
        assert "schema_info" in tables

def test_angel_one_normalizer():
    normalizer = AngelOneNormalizer()
    raw_data = [
        {
            "token": "26000",
            "symbol": "Nifty 50",
            "name": "NIFTY",
            "expiry": "",
            "strike": "0.000000",
            "lotsize": "75",
            "instrumenttype": "AMXIDX",
            "exch_seg": "NSE",
            "tick_size": "0.050000"
        },
        {
            "token": "1594",
            "symbol": "INFY-EQ",
            "name": "INFY",
            "expiry": "",
            "strike": "0.000000",
            "lotsize": "1",
            "instrumenttype": "",
            "exch_seg": "NSE",
            "tick_size": "0.050000"
        },
        {
            "token": "35002",
            "symbol": "NIFTY26JUL2624000CE",
            "name": "NIFTY",
            "expiry": "26JUL2026",
            "strike": "24000.000000",
            "lotsize": "75",
            "instrumenttype": "OPTIDX",
            "exch_seg": "NFO",
            "tick_size": "0.050000"
        }
    ]
    
    normalized = normalizer.normalize(raw_data)
    assert len(normalized) == 3
    
    # Check index mapping
    assert normalized[0]["symbol"] == "NSE:NIFTY_50"
    assert normalized[0]["name"] == "NIFTY_50"
    
    # Check equity mapping
    assert normalized[1]["symbol"] == "NSE:INFY"
    assert normalized[1]["name"] == "INFY"
    
    # Check option mapping
    assert normalized[2]["symbol"] == "NFO:NIFTY:2026-07-26:24000:CE"
    assert normalized[2]["expiry"] == "26JUL2026"
    assert normalized[2]["strike"] == 24000.0

def test_shoonya_normalizer():
    normalizer = ShoonyaNormalizer()
    raw_data = [
        {
            "Exchange": "NSE",
            "Token": "1594",
            "Symbol": "INFY",
            "TradingSymbol": "INFY-EQ",
            "LotSize": "1",
            "Instrument": "EQUITY",
            "TickSize": "0.05"
        },
        {
            "Exchange": "NFO",
            "Token": "35002",
            "Symbol": "NIFTY",
            "TradingSymbol": "NIFTY26JUL2624000CE",
            "LotSize": "75",
            "Expiry": "26-Jul-2026",
            "StrikePrice": "24000",
            "OptionType": "CE",
            "Instrument": "OPTIDX",
            "TickSize": "0.05"
        }
    ]
    
    normalized = normalizer.normalize(raw_data)
    assert len(normalized) == 2
    assert normalized[0]["symbol"] == "NSE:INFY"
    assert normalized[1]["symbol"] == "NFO:NIFTY:2026-07-26:24000:CE"

def test_stage_and_swap_instruments(setup_test_db):
    repo = setup_test_db
    
    instruments = [
        {
            "symbol": "NSE:INFY",
            "name": "INFY",
            "exch_seg": "NSE",
            "expiry": "",
            "strike": 0.0,
            "lotsize": 1,
            "instrumenttype": "EQUITY",
            "tick_size": 0.05,
            "description": "INFY-EQ",
            "metadata_json": "{}",
            "last_updated": "2026-07-04"
        }
    ]
    
    mappings = [
        {
            "symbol": "NSE:INFY",
            "broker_name": "ANGEL",
            "broker_token": "1594",
            "broker_symbol": "INFY-EQ",
            "last_updated": "2026-07-04"
        }
    ]
    
    sync_record = {
        "sync_id": "test-sync-123",
        "broker_name": "ANGEL",
        "master_version": "20260704",
        "source_hash": "hash123",
        "sync_timestamp": "2026-07-04T12:00:00",
        "records_added": 1,
        "records_updated": 0
    }
    
    repo.stage_and_swap_instruments("ANGEL", instruments, mappings, sync_record)
    assert repo.get_count() == 1
    assert repo.get_sync_hash("ANGEL") == "hash123"
    
    # Query lookups
    inst = repo.get_instrument_by_symbol("NSE:INFY")
    assert inst is not None
    assert inst["name"] == "INFY"
    
    token = repo.get_token_by_symbol("ANGEL", "NSE:INFY")
    assert token == "1594"
    
    inst_by_token = repo.get_instrument_by_token("ANGEL", "1594")
    assert inst_by_token is not None
    assert inst_by_token["symbol"] == "NSE:INFY"

def test_symbol_registry_lru_caching(setup_test_db):
    repo = setup_test_db
    
    # Insert a record
    instruments = [
        {"symbol": "NSE:INFY", "name": "INFY", "exch_seg": "NSE", "expiry": "", "strike": 0.0, "lotsize": 1, "instrumenttype": "EQUITY", "tick_size": 0.05, "description": "INFY-EQ", "metadata_json": "{}", "last_updated": "2026-07-04"}
    ]
    mappings = [
        {"symbol": "NSE:INFY", "broker_name": "ANGEL", "broker_token": "1594", "broker_symbol": "INFY-EQ", "last_updated": "2026-07-04"}
    ]
    sync_record = {"sync_id": "sync-1", "broker_name": "ANGEL", "master_version": "v1", "source_hash": "h1", "sync_timestamp": "2026", "records_added": 1, "records_updated": 0}
    repo.stage_and_swap_instruments("ANGEL", instruments, mappings, sync_record)
    
    registry = SymbolRegistry()
    registry.clear_cache()
    
    # First lookup (uncached, hits DB)
    sym1 = registry.get_symbol("1594")
    assert sym1 == "NSE:INFY"
    
    # Check cache info if lru_cache was used
    # Since we defined _cached_lookup inside _init_registry as lru_cache:
    info = registry._cached_lookup.cache_info()
    assert info.hits == 0
    assert info.misses == 1
    
    # Second lookup (cached, O(1) memory)
    sym2 = registry.get_symbol("1594")
    assert sym2 == "NSE:INFY"
    
    info2 = registry._cached_lookup.cache_info()
    assert info2.hits == 1

def test_broker_instrument_registry_fallback(setup_test_db):
    repo = setup_test_db
    broker_registry.clear_mock_registry()
    
    # Test DB path first
    instruments = [
        {"symbol": "NSE:INFY", "name": "INFY", "exch_seg": "NSE", "expiry": "", "strike": 0.0, "lotsize": 1, "instrumenttype": "EQUITY", "tick_size": 0.05, "description": "INFY-EQ", "metadata_json": "{}", "last_updated": "2026-07-04"}
    ]
    mappings = [
        {"symbol": "NSE:INFY", "broker_name": "ANGEL", "broker_token": "1594", "broker_symbol": "INFY-EQ", "last_updated": "2026-07-04"}
    ]
    sync_record = {"sync_id": "sync-1", "broker_name": "ANGEL", "master_version": "v1", "source_hash": "h1", "sync_timestamp": "2026", "records_added": 1, "records_updated": 0}
    repo.stage_and_swap_instruments("ANGEL", instruments, mappings, sync_record)
    
    inst = broker_registry.get("NSE:INFY")
    assert inst.symbol == "NSE:INFY"
    assert inst.exchange == "NSE"
    
    # Test In-Memory overlay registering (mocks taking priority)
    mock_inst = broker_registry.UniversalInstrument(symbol="NSE:INFY", exchange="NSE", description="MOCK DESCRIPTION")
    broker_registry.register(mock_inst)
    
    inst2 = broker_registry.get("NSE:INFY")
    assert inst2.description == "MOCK DESCRIPTION"
