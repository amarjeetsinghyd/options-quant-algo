# Project Brain System Core

## Purpose
Defines the global engineering workflow and principles for AI assistants operating in this repository.

## Non-Negotiable Principles
1. **Never analyze the entire codebase** unless explicitly requested. Always rely on Graph Retrieval.
2. **Deterministic Execution:** Every prompt MUST follow the pipeline in `workflow.md`.
3. **Modular Memory:** Never store all context in one file. Respect the domain boundaries in `memory/`.
4. **Graph is Truth:** Do not edit the graph structures manually. Rely on runtime tools to map dependencies.
5. **Incremental Sync:** Documentation is never fully regenerated. Only incremental changes are appended upon task completion.

## System Boundaries
- This file defines *how* the AI thinks, not *what* the project contains.
- Implementation details belong in `memory/`.
- Task history belongs in `tasks/`.
