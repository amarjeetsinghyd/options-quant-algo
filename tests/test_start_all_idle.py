"""Tests for the idle/wait behavior added to ``start_all.py``.

The original implementation exited the process at market close, which caused
PM2 (configured with ``autorestart: true``) to immediately restart the script,
creating an endless restart loop. The new implementation should gracefully shut
down services, enter an idle state until the next trading session, and then
restart the services without exiting the process.

These tests verify two aspects:

1. ``ProcessSupervisor._next_market_open`` correctly computes the next market
   open datetime (09:15) on a trading day, skipping non‑trading days.
2. ``ProcessSupervisor.monitor`` follows the idle path when the current time
   is after the configured market‑close hour. The test patches ``datetime.now``
   to a post‑close time, mocks ``is_trading_day`` and ``_next_market_open`` to
   control the wake‑up time, and replaces ``time.sleep`` with a no‑op to avoid
   real delays. It also replaces ``shutdown`` and ``start_all`` with stubs that
   record that they were called and force the monitor loop to exit.
"""

from datetime import datetime, timedelta
import importlib

import pytest


@pytest.fixture
def supervisor_module(monkeypatch):
    """Import ``start_all`` fresh for each test and ensure a clean monkeypatch
    environment.
    """
    module = importlib.import_module("start_all")
    importlib.reload(module)
    return module


def test_next_market_open_skips_non_trading_days(supervisor_module, monkeypatch):
    """``_next_market_open`` should return the next weekday at 09:15 when the
    current day is not a trading day.
    """
    start_all = supervisor_module

    # Simulate today being a Friday after market close (2026‑07‑02)
    fake_now = datetime(2026, 7, 2, 16, 0)
    monkeypatch.setattr(start_all.datetime, "now", lambda: fake_now)

    # Mock ``is_trading_day`` to return ``True`` only for the following Monday
    def fake_is_trading_day(date_obj):
        return date_obj == datetime(2026, 7, 5).date()

    monkeypatch.setattr(start_all, "is_trading_day", fake_is_trading_day)

    supervisor = start_all.ProcessSupervisor([])
    next_open = supervisor._next_market_open()
    expected = datetime(2026, 7, 5, 9, 15)  # Monday 09:15
    assert next_open == expected


def test_monitor_enters_idle_and_restarts(supervisor_module, monkeypatch):
    """When the current time is after market close, ``monitor`` should:

    1. Call ``shutdown`` to stop services.
    2. Sleep until the next market open (patched to a short interval).
    3. Call ``start_all`` to restart services.
    4. Continue the monitoring loop without exiting the process.
    """
    start_all = supervisor_module

    # Force ``datetime.now`` to a time after market close.
    fake_now = datetime(2026, 7, 2, 16, 0)
    monkeypatch.setattr(start_all.datetime, "now", lambda: fake_now)

    # ``is_trading_day`` is irrelevant for this path because we mock the
    # ``_next_market_open`` method directly, but we provide a simple stub.
    monkeypatch.setattr(start_all, "is_trading_day", lambda _: True)

    # Make ``_next_market_open`` return a time only a second in the future so
    # the idle loop finishes quickly.
    monkeypatch.setattr(
        start_all.ProcessSupervisor,
        "_next_market_open",
        lambda self: fake_now + timedelta(seconds=1),
    )

    # Replace ``time.sleep`` with a no‑op to avoid real waiting.
    monkeypatch.setattr(start_all.time, "sleep", lambda _: None)

    # Track calls to ``shutdown`` and ``start_all``.
    called = {"shutdown": False, "start_all": False}

    def fake_shutdown(self):
        called["shutdown"] = True
        # Signal the monitor loop to exit after the idle cycle.
        self._shutdown = True

    def fake_start_all(self):
        called["start_all"] = True

    monkeypatch.setattr(start_all.ProcessSupervisor, "shutdown", fake_shutdown, raising=False)
    monkeypatch.setattr(start_all.ProcessSupervisor, "start_all", fake_start_all, raising=False)

    supervisor = start_all.ProcessSupervisor([])
    # ``monitor`` will run until ``self._shutdown`` becomes True.
    supervisor.monitor()

    assert called["shutdown"] is True, "Supervisor.shutdown should be invoked"
    assert called["start_all"] is True, "Supervisor.start_all should be invoked after idle"
