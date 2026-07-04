# Changelog — Options Quant Algo Platform

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) and this project adheres to Semantic Versioning.

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
