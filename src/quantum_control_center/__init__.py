"""Quantum Control Center package.

This package provides a **UI‑Only** entry point that can operate in three
distinct modes:

1. ``UI_ONLY`` – launches the graphical user interface without any trading
   logic.  Useful for diagnostics, configuration, or demonstration purposes.
2. ``SIMULATION`` – runs the strategy in a simulated market environment.
3. ``LIVE_TRADING`` – connects to live market feeds and executes trades.

The implementation is deliberately lightweight and does **not** depend on
external UI frameworks; it simply prints status messages.  The surrounding
application (``start_all.py``) can import and instantiate the controller when
required.  Future extensions may replace the stub UI with a proper web or
desktop front‑end.
"""

from .manager import QuantumControlCenter, ControlMode

__all__ = ["QuantumControlCenter", "ControlMode"]