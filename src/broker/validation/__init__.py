"""Broker validation package.

Provides a generic entry point that selects a broker‑specific validation
script and returns a machine‑readable result (JSON). The package is deliberately
lightweight and broker‑neutral – new brokers can be added by extending the
``BROKER_VALIDATORS`` mapping in ``validator_factory.py``.
"""