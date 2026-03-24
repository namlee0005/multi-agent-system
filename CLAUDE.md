# Multi-Agent System Rules

This file defines how agents operate within the `multi-agent-system` framework.

## Task Protocol

The full Ben Protocol is defined in `SOUL.md`. The canonical pipeline is:

```
DETAIL → TEST-SPEC → IMPLEMENT → REVIEW → TEST-VALIDATE → DONE
```

1.  **Detailing:** The Architect MUST provide function signatures, data structures (Pydantic/TypeScript), and explicit file paths.
2.  **Test Spec:** The Tester generates executable test scripts against the Architect's spec BEFORE implementation begins.
3.  **Implementation:** Developer agents MUST use `<write_file path="PATH">CONTENT</write_file>` tags to ensure code is written to disk.
4.  **Self-Correction:** Agents have a maximum of 3 retry attempts to fix validation or code review failures.
5.  **Review:** All generated code artifacts are subject to a mandatory `CodeReviewer` agent check unless `--skip-review` is specified.
6.  **Test Validate:** The Tester reviews the implementation against the test spec. Test execution is required only if `--require-tests` is set.

## Code Standards

- **Precision:** Use `Numeric` or `Decimal` types for financial/monetary data. Never use `Float`.
- **Safety:** Sanitize all file paths to prevent path traversal. Writes are restricted to the project path.
- **Async:** Prefer async/await for I/O bound tasks (Binance feed, Database, Redis).
- **Logging:** Use the thread-safe `_log_lock` for all shared log file writes.

## Orchestration Flow

`SELECTING → PROPOSING → CHALLENGING → REVIEWING → SYNTHESIZING → DONE`

- **Parallelism:** Round agents run in parallel via `ThreadPoolExecutor`.
- **Persistence:** Every session creates a structured JSON log in `logs/session-{id}.json`.
- **Verification:** The human or Orchestrator must verify file existence and content after "completion".
