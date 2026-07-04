"""Central registry for broker‑related artifacts.

* **BrokerManifest** – static, immutable description of a broker.
* **BrokerRuntime** – mutable state that evolves during execution.
* **BrokerMetrics** – operational counters and latency aggregates.

The registry is a **singleton** accessed via module‑level functions.  The
factory (`src.broker.__init__.get_broker_adapter`) registers the adapter and
its manifest; the runtime and metrics objects are instantiated lazily and can
be updated by the adapter or by health‑monitoring components.
"""

from __future__ import annotations

from typing import Any, Optional

from .models.manifest import BrokerManifest
from .models.runtime import BrokerRuntime
from .models.metrics import BrokerMetrics
from .models.policy import BrokerPolicy

_manifest: Optional[BrokerManifest] = None
_runtime: Optional[BrokerRuntime] = None
_metrics: Optional[BrokerMetrics] = None
_policy: Optional[BrokerPolicy] = None
_adapter: Optional[Any] = None


def register_adapter(adapter: Any) -> None:
    """Register a concrete broker adapter.

    The adapter **must** expose a ``manifest`` attribute of type
    :class:`BrokerManifest`.  The function stores the adapter and its manifest
    in the module‑level singletons.
    """
    global _adapter, _manifest, _runtime, _metrics
    _adapter = adapter
    # The adapter is expected to provide a ``manifest`` property.
    _manifest = getattr(adapter, "manifest", None)
    if _manifest is None:
        raise AttributeError("Adapter does not expose a 'manifest' attribute")
    # Initialise mutable containers on first registration.
    _runtime = BrokerRuntime()
    _metrics = BrokerMetrics()
    _policy = BrokerPolicy()


def get_adapter() -> Any:
    if _adapter is None:
        raise RuntimeError("Broker adapter not registered")
    return _adapter


def manifest() -> BrokerManifest:
    if _manifest is None:
        raise RuntimeError("Broker manifest not registered")
    return _manifest


def runtime() -> BrokerRuntime:
    if _runtime is None:
        raise RuntimeError("Broker runtime not initialised")
    return _runtime


def metrics() -> BrokerMetrics:
    if _metrics is None:
        raise RuntimeError("Broker metrics not initialised")
    return _metrics


def policy() -> BrokerPolicy:
    """Return the lightweight :class:`BrokerPolicy` instance.

    The policy provides simple retry and operation‑allowance rules that can
    be consulted by services without needing the full manifest.
    """
    if _policy is None:
        raise RuntimeError("Broker policy not initialised")
    return _policy
