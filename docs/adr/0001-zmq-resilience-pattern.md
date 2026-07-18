# ADR 0001: ZeroMQ Socket Resilience Pattern

- **Status**: Accepted
- **Date**: 2026-07-16
- **Hotfix**: 1.0.1-hotfix
- **Author**: GitHub Copilot (glm-5.2)

## Context

The trading engine runs on an Oracle Cloud VPS with 1 GB RAM and 2 CPU cores. Under sustained memory pressure, ZeroMQ sockets in `src/core/message_bus.py` would enter an `ENOTSOCK` state — the socket handle becomes invalid but the Python object still exists. This caused:

1. **Publisher failures**: `send()` calls raised `zmq.error.ZMQError: Socket operation on non-socket`, crashing the command publisher.
2. **Subscriber failures**: `poll()` returned `ENOTSOCK`, causing the feed listener thread to crash and the brain service to lose all market data feeds.
3. **Cascading restart loop**: PM2 restarted `quant-engine` on crash, but the same socket corruption recurred within minutes, resulting in **35 restarts** before the hotfix was applied.

The root cause was that each `MessageBusPublisher` and `MessageBusSubscriber` instance created its own `zmq.Context()`. When one socket closed (either explicitly or due to error recovery), it could terminate the context, invalidating other sockets sharing that context. Additionally, there was no automatic recovery path — once a socket entered `ENOTSOCK`, it stayed broken.

## Decision

### 1. Shared Context Singleton
Both `MessageBusPublisher` and `MessageBusSubscriber` now use `zmq.Context.instance()` instead of creating per-instance contexts. This process-wide singleton is shared across all ZMQ users and is never terminated by individual socket `close()` calls.

### 2. Socket Recovery Pattern
Each class implements a three-method lifecycle:
- `_init_socket()`: Creates the socket, sets options (LINGER, RCVHWM/SNDHWM), and binds/connects.
- `_reconnect()`: Closes the old socket (if it exists), calls `_init_socket()`, and re-registers with the poller (Subscriber only).
- `_closed` flag: Prevents reconnect attempts after explicit shutdown.

### 3. Publisher: Two-Attempt Publish
The Publisher's `publish()` method attempts to send. On `ENOTSOCK`, it calls `_reconnect()` and retries once. If the second attempt also fails, the message is dropped (logged as warning) rather than crashing the process.

### 4. Subscriber: Poller Re-registration and Topic Re-subscription
The Subscriber's `listen()` loop detects `ENOTSOCK` during `poller.poll()`, calls `_reconnect()`, and re-subscribes to all tracked topics (`self._topics` set). This ensures no data loss after recovery.

### 5. Graceful Close
`close()` sets `socket.linger = 0` (discard unsent messages immediately) and closes the socket. It does NOT call `context.term()` — the shared context is left intact for other components.

### 6. DataFrame Duplicate Column Guard
A related issue: Shoonya API responses occasionally contained duplicate `timestamp` columns, causing `df['timestamp']` to return a DataFrame instead of a Series, which broke downstream dtype operations. A defensive guard is now applied at all DataFrame ingestion points:
```python
df = df.loc[:, ~df.columns.duplicated()]
ts_col = df['timestamp']
if isinstance(ts_col, pd.DataFrame):
    ts_col = ts_col.iloc[:, 0]
```

## Consequences

### Positive
- **Stability**: The 35-restart crash loop is eliminated. The engine now self-heals from transient ZMQ socket corruption.
- **No data loss**: Subscriber re-subscribes to all topics after recovery, minimizing feed gaps.
- **Memory efficiency**: Shared context reduces memory overhead vs. per-instance contexts.
- **Forward compatibility**: Future ZMQ users in the process automatically benefit from the shared context.

### Negative
- **Silent message drops**: If the Publisher's second publish attempt fails, the message is dropped. This is acceptable for tick data (next tick arrives in milliseconds) but would need a retry queue for critical command messages.
- **No context cleanup**: The shared context is never explicitly terminated. This is fine for a long-running daemon process but could leak in test environments. Tests should use `zmq.Context.instance().term()` in teardown if needed.

## Files Modified
- `src/core/message_bus.py` — Full rewrite of `MessageBusPublisher` and `MessageBusSubscriber`
- `src/broker/adapters/shoonya_adapter.py` — DataFrame guard in `ShoonyaHistoricalProvider.get_historical()`
- `src/services/brain_service.py` — DataFrame guard in BootGapFill block
- `src/execution/execution_manager.py` — Defensive alias `self.current_trade = None`

## References
- `ARCHITECTURE.md` Section 4 — Message Bus Resilience Pattern
- `CHANGELOG.md` → `[1.0.1-hotfix]`
- `docs/PROJECT_STATE.md` — Last Engine Restart: 2026-07-16
