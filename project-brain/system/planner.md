# Planner Engine

## Responsibilities
Before any code execution begins, the Planner must generate an explicit plan artifact containing:

1. **Goal:** Clear definition of success.
2. **Affected Modules:** Determined via Graph Retrieval.
3. **Execution Order:** Step-by-step logic sequence.
4. **Complexity Estimation:** Low, Medium, High.
5. **Risk Assessment:** What could break? (Especially around the Zero-Trust Architecture).
6. **Rollback Strategy:** How to undo if static validation fails.

## Rule
Only after planning is approved by the user (or statically validated) does execution begin.
