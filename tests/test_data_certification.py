import os
import json
import pytest
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch
from src.services.indicator_audit_service import IndicatorAuditService, INDICATOR_TOLERANCES
from src.services.maintenance_service import MaintenanceService

def test_independent_math_calculations():
    # Setup simple synthetic arrays
    closes = np.array([100.0, 101.0, 102.0, 101.5, 103.0, 102.5, 104.0, 105.0, 104.5, 106.0])
    highs = closes + 1.0
    lows = closes - 1.0
    volumes = np.array([100, 150, 120, 200, 180, 220, 190, 210, 170, 250], dtype=float)

    # 1. Test EMA 9
    alpha = 2.0 / (9 + 1)
    ref_ema = np.zeros_like(closes)
    ref_ema[0] = closes[0]
    for i in range(1, len(closes)):
        ref_ema[i] = (closes[i] * alpha) + (ref_ema[i-1] * (1.0 - alpha))
        
    assert ref_ema[0] == 100.0
    assert abs(ref_ema[1] - 100.2) < 1e-5

    # 2. Test VWAP
    typical_price = (highs + lows + closes) / 3.0
    cum_pv = np.cumsum(typical_price * volumes)
    cum_v = np.cumsum(volumes)
    ref_vwap = cum_pv / cum_v
    
    assert ref_vwap[0] == closes[0]

def test_audit_tolerances():
    # Verify indicator tolerances dict schema
    assert INDICATOR_TOLERANCES["close"] == 0.00
    assert INDICATOR_TOLERANCES["vwap"] == 0.02
    assert INDICATOR_TOLERANCES["vfi"] == 0.05

@patch('src.services.indicator_audit_service.write_json_atomic')
@patch('src.services.indicator_audit_service.os.path.exists')
def test_audit_service_run_graceful_fallback(mock_exists, mock_write):
    mock_exists.return_value = False
    service = IndicatorAuditService()
    
    # Run audit on a date with no files
    # It should not crash, it should return a FAILED report with root causes listed
    report = service.run_daily_audit(date_str="2026-07-05")
    assert report["market_date"] == "2026-07-05"
    assert report["research_certification"] == "FAILED"
    assert "Missing Indicator Data" in report["root_causes"]
    assert mock_write.called

@patch('src.services.maintenance_service.logger')
def test_reordered_eod_tasks(mock_logger):
    # Reorder EOD sequence test
    # Reorder: Gap Fill -> Indicator Audit -> Certification -> Summary Generation -> Cloud Backup -> Local Cleanup
    service = MaintenanceService()
    
    called_order = []
    
    def mock_gf(*args, **kwargs): called_order.append("gap_fill")
    def mock_audit(*args, **kwargs): called_order.append("audit")
    def mock_sum(*args, **kwargs): called_order.append("summary")
    def mock_arch(*args, **kwargs): called_order.append("archiver")
    def mock_val(*args, **kwargs): called_order.append("validator")
    def mock_backup(*args, **kwargs): called_order.append("backup")
    def mock_sync(*args, **kwargs): called_order.append("sync")

    with patch('src.services.gap_fill_service.run_gap_fill', side_effect=mock_gf), \
         patch('src.services.indicator_audit_service.run_daily_audit', side_effect=mock_audit), \
         patch('src.utils.summary_generator.generate_daily_summary', side_effect=mock_sum), \
         patch('src.utils.parquet_archiver.archive_ml_database', side_effect=mock_arch), \
         patch('src.utils.parquet_archiver.compress_institutional_memory', side_effect=mock_arch), \
         patch('src.ml_engine.eod_validator.run_eod_validation', side_effect=mock_val, create=True), \
         patch('src.services.cloud_backup.run_backup', side_effect=mock_backup), \
         patch('src.services.instrument_sync_service.run_sync', side_effect=mock_sync):
         
        service._run_eod_tasks()
        
    expected_order = ["gap_fill", "audit", "summary", "archiver", "archiver", "validator", "backup", "sync"]
    assert called_order == expected_order
