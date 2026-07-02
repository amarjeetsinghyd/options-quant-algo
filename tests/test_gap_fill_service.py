import os
import sys
import types
from pathlib import Path
import pandas as pd

import pytest

# Stub Angel One connection dependency to avoid requiring pyotp during unit tests.
fake_angel_conn = types.ModuleType("src.core.angel_connection")
def fake_get_angel_connection():
    return None, None
fake_angel_conn.get_angel_connection = fake_get_angel_connection
sys.modules["src.core.angel_connection"] = fake_angel_conn

from src.services import gap_fill_service


@pytest.fixture(autouse=True)
def patch_pd_read_parquet(monkeypatch):
    def fake_read_parquet(path):
        if isinstance(path, (str, Path)) and str(path).endswith("synthetic_volume_boot.parquet"):
            return pd.DataFrame({
                "timestamp": [pd.Timestamp("2026-07-01 09:15:00")],
                "open": [100],
                "high": [110],
                "low": [95],
                "close": [105],
                "volume": [1000]
            })
        raise FileNotFoundError(f"No such file: {path}")

    monkeypatch.setattr(gap_fill_service.pd, "read_parquet", fake_read_parquet)
    return monkeypatch


def test_is_cache_current_returns_false_when_missing(tmp_path):
    monkey_file = tmp_path / "synthetic_volume_boot.parquet"
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gap_fill_service, "CACHE_FILE", monkey_file)

    try:
        assert not gap_fill_service.is_cache_current()
        assert gap_fill_service.load_cached_boot_dataframe() is None
    finally:
        monkeypatch.undo()


def test_load_cached_boot_dataframe_reads_parquet(tmp_path):
    monkey_file = tmp_path / "synthetic_volume_boot.parquet"
    monkey_file.write_text("")

    expected_df = pd.DataFrame({"timestamp": ["2026-07-01 09:15:00"], "open": [100], "high": [110], "low": [95], "close": [105], "volume": [1000]})
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gap_fill_service, "CACHE_FILE", monkey_file)
    monkeypatch.setattr(gap_fill_service.pd, "read_parquet", lambda path: expected_df)

    try:
        loaded = gap_fill_service.load_cached_boot_dataframe()
        assert loaded is not None
        assert list(loaded.columns) == ["timestamp", "open", "high", "low", "close", "volume"]
        assert loaded.iloc[0]["open"] == 100
    finally:
        monkeypatch.undo()
