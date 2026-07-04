# Broker package initializer
# Provides a factory to obtain a broker adapter based on configuration.

from importlib import import_module
from typing import Any

from src.config.engineering_config import BROKER
from .registry import register_adapter


def get_broker_adapter() -> Any:
    """Return an instance of the configured broker adapter.

    The ``BROKER`` setting (default ``ANGEL``) determines which concrete
    adapter class is imported from ``src.broker.adapters``.
    """
    broker_name = BROKER.upper()
    if broker_name == "ANGEL":
        module = import_module("src.broker.adapters.angel_one_adapter")
        adapter = module.AngelOneAdapter()
        register_adapter(adapter)
        return adapter
    elif broker_name == "SHOONYA":
        module = import_module("src.broker.adapters.shoonya_adapter")
        adapter = module.ShoonyaAdapter()
        register_adapter(adapter)
        return adapter
    else:
        raise ValueError(
            f"Unsupported broker '{BROKER}'. Supported values: ANGEL, SHOONYA"
        )
