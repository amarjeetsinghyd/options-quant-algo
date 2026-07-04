"""Tests for the transition-aware, policy-driven LifecycleManager.

These tests verify that:
1. StandardNSEMarketPolicy correctly determines scheduled transition times, skipping non-trading days.
2. LifecycleManager handles transitions between OFFLINE, TRADING_IDLE, and TRADING_LIVE states.
3. The monitor loop detects state changes and calls transition_to_state.
"""

from datetime import datetime, timedelta
import importlib
import pytest
from start_all import LifecycleManager, StandardNSEMarketPolicy, SERVICES

@pytest.fixture
def supervisor_module(monkeypatch):
    """Import ``start_all`` fresh for each test and ensure a clean monkeypatch
    environment.
    """
    module = importlib.import_module("start_all")
    importlib.reload(module)
    return module

def test_next_market_open_skips_non_trading_days(supervisor_module, monkeypatch):
    """``next_scheduled_transition`` should return the next trading day at 09:15 when the
    current day is a weekend/holiday.
    """
    start_all = supervisor_module

    # Simulate Friday after market close (2026-07-02)
    fake_now = datetime(2026, 7, 2, 16, 0)
    monkeypatch.setattr(start_all.datetime, "now", lambda: fake_now)

    # Mock ``is_trading_day`` to return ``True`` only for the following Monday
    def fake_is_trading_day(date_obj):
        return date_obj == datetime(2026, 7, 5).date()

    monkeypatch.setattr(start_all, "is_trading_day", fake_is_trading_day)

    policy = start_all.StandardNSEMarketPolicy()
    next_transition = policy.next_scheduled_transition(fake_now)
    expected = datetime(2026, 7, 5, 9, 15)  # Monday 09:15
    assert next_transition == expected

def test_monitor_enters_idle_and_restarts(supervisor_module, monkeypatch):
    """When a state transition is detected, the monitor loop should trigger transition_to_state."""
    start_all = supervisor_module

    # Force ``datetime.now`` to a weekend
    fake_now = datetime(2026, 7, 4, 12, 0)
    monkeypatch.setattr(start_all.datetime, "now", lambda: fake_now)

    # Track calls
    transition_calls = []

    def fake_transition_to_state(self, new_state, reason):
        transition_calls.append(new_state)
        self.current_state = new_state
        # Stop loop after first execution to prevent infinite test loop
        self._shutdown = True

    monkeypatch.setattr(start_all.LifecycleManager, "transition_to_state", fake_transition_to_state)
    monkeypatch.setattr(start_all.time, "sleep", lambda _: None)

    manager = start_all.LifecycleManager([])
    manager.monitor()

    assert "OFFLINE" in transition_calls
