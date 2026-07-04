"""Quantum Control Center – core manager.

The **Quantum Control Center (QCC)** is a new, independent component that
provides three operational modes while re‑using the existing infrastructure:

* **UI_ONLY** – launches a minimal user‑interface (currently a console UI).
* **SIMULATION** – runs the algorithmic engine against a simulated market.
* **LIVE_TRADING** – runs the engine against live market data.

The design deliberately avoids any heavyweight UI libraries so that the
module can be added without pulling additional dependencies.  It can be
extended later with a proper web UI or desktop framework.

The manager is intentionally simple: it validates the requested mode,
initialises required services via the existing ``LifecycleManager`` (or the
legacy ``ProcessSupervisor`` alias) and provides hooks for future UI
integration.
"""

from __future__ import annotations

import enum
import logging
from typing import List, Optional

from src.utils.logger import get_logger

# Import the legacy alias so existing code that expects ``ProcessSupervisor``
# continues to work.  ``LifecycleManager`` is the actual implementation.
import start_all

logger = get_logger("quantum_control_center")


class ControlMode(str, enum.Enum):
    """Supported operation modes for the Quantum Control Center."""

    UI_ONLY = "ui_only"
    SIMULATION = "simulation"
    LIVE_TRADING = "live_trading"

    @classmethod
    def from_str(cls, value: str) -> "ControlMode":
        """Convert a case‑insensitive string to a :class:`ControlMode`.

        Raises:
            ValueError: If *value* does not correspond to a known mode.
        """
        try:
            return cls(value.lower())
        except ValueError as exc:
            raise ValueError(f"Unsupported control mode: {value}") from exc


class QuantumControlCenter:
    """High‑level orchestrator for the three QCC modes.

    The class is deliberately lightweight – it does not start any services on
    import.  Consumers should instantiate the class and call :meth:`run` with the
    desired mode.
    """

    def __init__(self, services: Optional[List[dict]] = None):
        # ``services`` mirrors the structure used by ``start_all``.  If the
        # caller does not provide a custom list we fall back to the default
        # configuration defined in ``start_all``.
        self.services = services if services is not None else start_all.SERVICES
        # Use the legacy alias for compatibility with existing tests and code.
        self.supervisor = start_all.ProcessSupervisor(self.services)

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------
    def run(self, mode: ControlMode) -> None:
        """Execute the QCC in the specified *mode*.

        Args:
            mode: The :class:`ControlMode` to run.
        """
        logger.info("Quantum Control Center starting in %s mode", mode.value)
        if mode is ControlMode.UI_ONLY:
            self._run_ui()
        elif mode is ControlMode.SIMULATION:
            self._run_simulation()
        elif mode is ControlMode.LIVE_TRADING:
            self._run_live_trading()
        else:  # pragma: no cover – defensive programming
            raise ValueError(f"Unhandled control mode: {mode}")

    # ---------------------------------------------------------------------
    # Private helpers for each mode
    # ---------------------------------------------------------------------
    def _run_ui(self) -> None:
        """Start the minimal UI.

        For now this simply prints a banner and lists the available services.
        Future work can replace this with a proper web or desktop UI.
        """
        print("=== Quantum Control Center – UI Only ===")
        print("Available services:")
        for svc in self.services:
            print(f" * {svc['name']}")
        print("(UI placeholder – extend as needed)")

    def _run_simulation(self) -> None:
        """Run the engine in simulation mode.

        The simulation mode starts all services via the supervisor.  The
        ``feed_service`` (or any service that respects the ``SIMULATION``
        environment variable) can detect the mode and use mock market data.
        """
        # Inject an environment flag so downstream services can detect the
        # simulation context.
        import os

        os.environ["QCC_MODE"] = ControlMode.SIMULATION.value
        self.supervisor.start_all()
        try:
            self.supervisor.monitor()
        finally:
            self.supervisor.shutdown()

    def _run_live_trading(self) -> None:
        """Run the engine against live market data.

        Live mode clears the ``QCC_MODE`` flag so services operate with their
        default production behaviour.
        """
        import os

        os.environ.pop("QCC_MODE", None)
        self.supervisor.start_all()
        try:
            self.supervisor.monitor()
        finally:
            self.supervisor.shutdown()
