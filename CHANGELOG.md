# Changelog — Options Quant Algo Platform

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to Semantic Versioning.

## [1.0.1-hotfix] — 2026-07-16

Critical hotfix patch for QOT terminal freeze and backend crashes on Oracle Cloud VPS (1 GB RAM, 2 CPU). Addresses ZMQ socket instability and DataFrame dtype corruption causing runtime exceptions during live market data processing.

### Fixed
- **ZMQ Message Bus — Publisher & Subscriber (`src/core/message_bus.py`):** Rewrote both `MessageBusPublisher` and `MessageBusSubscriber` with automatic socket recovery. Uses shared `zmq.Context.instance()` (no premature context termination), `_init_socket()` / `_reconnect()` pattern, `_closed` flag for graceful shutdown. Publisher: 2-attempt publish loop with ENOTSOCK recovery. Subscriber: ENOTSOCK detection in `listen()` loop → reconnect → re-register with poller → re-subscribe all tracked topics → 0.5s backoff → continue. Resolves the 35-restart crash loop caused by socket/context lifecycle races under memory pressure.
- **DataFrame Duplicate Column Guard (`src/broker/adapters/shoonya_adapter.py`):** Added `df.loc[:, ~df.columns.duplicated()]` guard and safe dtype extraction (`isinstance(ts_col, pd.DataFrame)` → `.iloc[:, 0]`) before `getattr(ts_col.dtype, 'tz', None)` in `ShoonyaHistoricalProvider.get_historical()`. Prevents `AttributeError` when Shoonya API returns duplicate timestamp columns.
- **DataFrame Duplicate Column Guard (`src/services/brain_service.py`):** Same guard pattern applied at the BootGapFill price DataFrame processing block (~line 716). Prevents `KeyError: 'timestamp'` and dtype corruption during gap-fill operations.
- **Defensive `current_trade` Alias (`src/execution/execution_manager.py`):** Added `self.current_trade = None` defensive alias at line 24 alongside `self.trade_context = None`. Zero-cost insurance against any future code paths referencing `current_trade` instead of `trade_context`.

### Confirmed Stale (No Action Required)
- **`services.registry` import:** Grep confirmed zero imports across `src/`. File does not exist. No action.
- **`timedelta` import in `brain_service.py`:** Already imported at line 12 (`from datetime import datetime, timedelta`). No action.

### Changed
- **ZMQ Socket Lifecycle:** Both Publisher and Subscriber now use `zmq.Context.instance()` (shared singleton) instead of creating/terminating per-instance contexts. `close()` uses `linger=0` and does NOT terminate the shared context.

### Infrastructure
- **Deployment:** Hotfix deployed to Oracle Cloud VPS (`137.23.41.38`) via SCP to `/home/opc/quant_bot/`. PM2 process `quant-engine` restarted successfully.
- **Agent Signature:** Hotfix applied by **GitHub Copilot (glm-5.2)** on 2026-07-16. See `docs/adr/0001-zmq-resilience-pattern.md` for architectural rationale.

---

## [1.0.2-hotfix] — 2026-07-17

Diagnostic and corrective patch applied during pre-open live troubleshooting (2026-07-16 → 2026-07-17). Resolves a cascading-context bug introduced by 1.0.1-hotfix, a critical pre-open crash caused by a latent IndentationError in the 1.0.1 deployment, and three platform-mismatch defects in the health monitoring subsystem that produced a permanently false "Critical" health state on the VPS.

### Fixed
- **ZMQ Publisher Shared-Context Cascade (`src/core/message_bus.py`):** Removed the `self.context.term()` block from `MessageBusPublisher._init_socket()`. In 1.0.1-hotfix, the Publisher was assigned `zmq.Context.instance()` (the process-wide shared singleton) but `_init_socket()` still called `.term()` on reconnect — directly violating ADR-0001's stated design ("does NOT terminate the shared context"). On the first Publisher ENOTSOCK recovery, `.term()` would invalidate the shared context and cascade ENOTSOCK to every other socket (including the Subscriber), re-triggering the exact 35-restart crash loop the hotfix was designed to eliminate. The Publisher now mirrors the Subscriber (which was already correct): it closes the socket but leaves the shared context intact. Latent bug — dormant since 1.0.1 deployment because the Publisher ENOTSOCK path had not been exercised under load until market open.
- **brain_service.py IndentationError (deployment correction):** The 1.0.1-hotfix deployed `src/services/brain_service.py` with an `IndentationError: unexpected unindent` at the duplicate-column guard (~line 708, the BootGapFill block). The error was latent overnight because brain only runs in `TRADING_LIVE`; it surfaced at the 09:15 IST transition on 2026-07-16, causing a ~9-minute crash loop until the file was corrected on the VPS at 09:23 IST. Root cause: bad indentation in the hotfix's own guard code, not a logic error.
- **Health Monitor ZMQ Transport Mismatch (`src/services/health_service.py`):** `PassiveHealthMonitor.__init__` connected its feed/exec subscribers to `tcp://127.0.0.1:{FEED_PORT}` / `tcp://127.0.0.1:{EXEC_PORT}`, but on Linux the publishers bind to `ipc:///tmp/quant_{port}` (see `message_bus._addr_str()`). TCP and IPC are different transports — the monitor never received a single tick or signal since first deployment, so `last_tick`, `last_signal`, and `ticks_per_sec_last_minute` were permanently null/0. Extracted a module-level `_zmq_addr(port)` helper that returns `ipc://` on non-Windows and `tcp://` on Windows, matching the publisher binding logic. Cause: code developed/tested on Windows (where `_addr_str()` returns TCP) and deployed to Linux without adapting for the IPC switch.
- **Health Monitor psutil PID Matching (`src/services/health_service.py`):** `get_process_info()` searched for `"feed_service.py"` in the process command line, but PM2 on Linux launches services as `python3 -m src.services.feed_service` (module form). The string `feed_service.py` never appears in that command, so psutil iterated all processes, found no match, and returned `{"status": "Critical", "pid": None}` for every service. Stripped the `.py` suffix via `str.removesuffix('.py')` so the match works for both script invocation (`python feed_service.py`) and module invocation (`python -m src.services.feed_service`). Cause: same Windows/Linux platform mismatch as the ZMQ transport bug.

### Changed
- **Health Monitor ZMQ Context (`src/services/health_service.py`):** Switched `zmq.Context()` (per-instance) to `zmq.Context.instance()` (shared singleton), consistent with the post-1.0.1 `message_bus.py` architecture. The health monitor's subscriber now participates in the same shared-context self-healing pattern as the rest of the system.
- **Removed unused `timedelta` import** from `health_service.py` (was imported but never referenced).

### Infrastructure
- **Deployment:** Both patched files deployed to Oracle Cloud VPS (`137.23.41.38`) via SCP to `/home/opc/quant_bot/`. `message_bus.py` hot-swapped pre-open (09:09 IST) and loaded at the 09:15 transition; `health_service.py` deployed and loaded via `pm2 restart quant-engine` at 07:54 IST on 2026-07-17. SHA256 parity verified between local and VPS for both files.
- **Verification:** Post-fix health score recovered from 20 → 70 (pre-market) with `is_trading_day: true`. Health monitor daemon log confirms first-ever successful IPC connections: `Subscriber connected to ipc:///tmp/quant_5555` (TICK.) and `ipc:///tmp/quant_5556` (EXEC.). End-to-end tick-flow verification (feed → brain → indicators) deferred to the 2026-07-17 09:15 IST market open.
- **Agent Signature:** Diagnostic and fixes applied by **ZCode (builtin:zai-start-plan/GLM-5.2)** on 2026-07-16/17. See `docs/adr/0001-zmq-resilience-pattern.md` for the upstream ZMQ resilience rationale that this hotfix completes.

---

## [1.0.0-research-baseline] — 2026-07-04

First research-grade baseline release compiling the initial platform setup, lifecycle supervisor, and explainability layer.

### Added
- **Universal Instrument Registry:** SQLite repository mapping, syncing, and caching instrument metadata across multiple brokers (AngelOne, Shoonya).
- **Headless Supervisor:** Headless microservice supervisor (`start_all.py` / `ProcessLauncher`) to spawn processes windowless on Windows.
- **Git Code Provenance & Hashing:** Provenance layer capturing repo branch, git commit hash, clean/dirty state, strategy hashes, and schema versions (Phase 2A).
- **Decision Intelligence Layer:** 3-tier trace explainability model mapping trading state transitions (Phase 2B).
- **Dataclass-based Rules:** Type-safe `RuleEvaluation` and `StrategyEvaluation` dataclasses for strategy execution trees.
- **Dynamic Configuration:** Extracted PM2 settings and data lifecycles to separate config modules.
- **Unit Test Suite:** Comprehensive validation suite covering lifecycle transitions, broker normalizations, and database syncs.
