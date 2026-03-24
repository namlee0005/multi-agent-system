# SOUL.md — MAS Operating Principles

This file defines the Ben Protocol: the canonical workflow governing how implementation tasks move through the Multi-Agent System. It is the authoritative source for agent sequencing, gate conditions, and completion criteria.

---

## Project Workflow (The Ben Protocol)

Every implementation task follows a six-stage pipeline. The Tester agent participates at two points: once during detailing (to produce executable acceptance criteria before code is written) and once after implementation (to validate the artifact).

```
DETAIL -> TEST-SPEC -> IMPLEMENT -> REVIEW -> TEST-VALIDATE -> DONE
```

### Stage 1: DETAIL (Architect)

The Architect produces:
- Function signatures and data structures (Pydantic / TypeScript / Go structs)
- Explicit file paths for all outputs
- Service boundaries and integration contracts
- A tasks.md written to disk using a write_file tag

**Gate:** Task is not handed to a Developer until all signatures and file paths are explicit. Vague detailing is returned to the Architect.

### Stage 2: TEST-SPEC (Tester)

Before any implementation begins, the Tester reads the Architect's detail output and produces:
- Named test functions with concrete assertions (not prose)
- Required fixtures and environment variables
- `# FAST (<1s)` / `# SLOW (>5s)` labels on each test
- A test file written to disk at `tests/test_MODULE.py` using a write_file tag

**Rationale:** Writing tests against signatures — not implementations — forces acceptance criteria to be concrete. Untestable designs are flagged here, before any code is written.

**Gate:** If the Tester flags a component as untestable without full system setup, the Architect must revise the design before implementation proceeds.

### Stage 3: IMPLEMENT (Developer agent)

Developer agents implement against the Architect's specifications and the Tester's test file. All outputs are written to disk using write_file tags.

**Maximum 3 retry attempts** to fix validation failures before the task is escalated.

### Stage 4: REVIEW (CodeReviewer)

All generated code artifacts are subject to the mandatory CodeReviewer gate (unless `--skip-review` is specified).

CodeReviewer output: `{"status": "PASS"|"WARN"|"FAIL", "issues": [], "suggestion": "..."}`

**Gate:** FAIL returns to Stage 3 (counts against the 3-retry budget). WARN proceeds with issues logged. PASS advances.

### Stage 5: TEST-VALIDATE (Tester)

The Tester reviews the final implementation against the test spec from Stage 2 and reports:
- Which test cases are satisfied by the implementation
- Any edge cases the implementation misses
- Whether the test scripts are runnable as-written

**Execution gate (conditional):**
- If `--require-tests` is set: tests must execute and pass. Failure returns to Stage 3.
- If `--require-tests` is not set (default): Tester produces a PASS/WARN/FAIL judgment on test coverage quality only. FAIL returns to Stage 3; WARN is logged and proceeds.

**Rationale:** Requiring green test execution as a hard default would block the pipeline on environment issues (no DB, no exchange sandbox). Execution is opt-in.

### Stage 6: DONE

Task is complete when:
1. CodeReviewer status is PASS or WARN
2. Tester status is PASS or WARN (execution required only if `--require-tests`)
3. All output artifacts are verified to exist on disk
4. Session log entry has `end_time` written

---

## Agent Roles in the Ben Protocol

| Stage | Agent | Output |
|-------|-------|--------|
| DETAIL | Architect | tasks.md, function signatures, data models |
| TEST-SPEC | Tester | tests/test_MODULE.py with named assertions |
| IMPLEMENT | BackendDev / FrontendDev / DevOps | Implementation files |
| REVIEW | CodeReviewer | JSON PASS/WARN/FAIL |
| TEST-VALIDATE | Tester | Coverage judgment; execution if --require-tests |

---

## Flags

| Flag | Effect |
|------|--------|
| `--skip-review` | Bypasses CodeReviewer gate (Stage 4) |
| `--require-tests` | Promotes test execution to a hard gate (Stage 5) |
| `--dry-run` | Runs pipeline without writing files to disk |

---

## Invariants

These rules apply at every stage and cannot be overridden by agent proposals:

- **Decimal, not Float:** All monetary and quantity fields use `Decimal` / `NUMERIC`. No exceptions.
- **Path safety:** All file writes are sanitized via `Path.resolve()` + `startswith(project_path)`. Writes outside the project root are dropped.
- **Async I/O:** All database, network, and filesystem operations use async/await.
- **Log safety:** All shared log file writes use `_log_lock`.
- **Additive rule:** New stages and gates are added to this protocol; existing stages are never silently removed.