# MAS Implementation Tasks

## Completed

- [x] Phase 1: Snapshot Key Filtering — `ContextStore.snapshot(keys=[...])` filtering
- [x] Phase 2: Compression Gate — `_compress_proposals()` with `## Summary` extraction
- [x] Phase 3: Spec Content Deduplication — `self.spec_content` cached at init
- [x] Phase 4: SDK Migration + Prompt Caching — *superseded by Phase 6*
- [x] Phase 5: Skills System — per-agent `SKILL.md` injection with token cap enforcement
- [x] Phase 6: CLI Session Persistence — implemented with `SessionStore` and `CLISession`
- [x] **7.1 — CLAUDECODE env strip enforcement audit:** Unit tests implemented and passing.
- [x] **7.2 — Session invalidation on synthesis completion:** Implemented via try/finally in orchestrator.
- [x] **7.3 — Gemini stateless enforcement:** Assertions added to prevent unsafe resume.
- [x] **7.4 — --resume retry contract implementation:** Recursive retry with depth guard implemented.
- [x] **7.5 — Benchmark gate (BLOCKING):** ROI analysis confirmed significant token savings via cache.
- [x] **7.6 — CLICallResult completeness validation:** All observability fields (tokens, duration, resume) are logged.
- [x] **7.7 — Skills token cap CI enforcement:** `scripts/lint_skills.py` integrated and verified using `tiktoken`.
- [x] **8.1 — Structured error taxonomy:** Created `exceptions.py` with typed MASError hierarchy.
- [x] **8.2 — Session log integrity check:** Orchestrator now warns if the previous session was interrupted.
- [x] **8.3 — Skill injection observability:** Surface `skills_injected: true/false` directly in CLI output summaries.
- [x] **8.4 — Regression test suite:** Full end-to-end flow test covering all core components.
- [x] **8.5 — Path Standardization & Root Cleanup:** Enforced `reports/` directory for all outputs and cleaned MAS root.
- [x] **8.6 — Project Creation & Pathing Logic Fix:** Updated `create_project.sh` and agent prompts to ensure clean, relative project structures.
- [x] **9.1 — FunctionalSkill & ToolParam models:** `skills/functional/models.py` — Pydantic v2 contracts for tools, calls, and results.
- [x] **9.2 — skills/registry.yaml:** Initial registry with `web_search`, `read_file`, `list_dir`, `run_python`.
- [x] **9.3 — SkillRegistry class:** `skills/functional/registry.py` — loads yaml, filters by agent, generates schema blocks.
- [x] **9.4 — ToolInterceptor:** `skills/functional/interceptor.py` — parses `[TOOL_CALL: name | {args}]` markers.
- [x] **9.5 — read_file & list_dir tools:** `skills/functional/tools.py` — realpath + prefix guard on all file access.
- [x] **9.6 — run_python tool:** `skills/functional/tools.py` — subprocess with timeout, no shell=True.
- [x] **9.7 — CLISession interception loop:** `backends/cli_session.py` — intercept, execute, resume cycle (max 5 rounds).
- [x] **10.1 — WorkflowState three-layer model:** `workflow/state.py` — conversation / task / world layers.
- [x] **10.2 — WorkflowGraph DAG engine:** `workflow/graph.py` — topological execution with handler dispatch.
- [x] **10.3 — ConsensusEvaluator:** `workflow/consensus.py` — Jaccard keyword overlap for early-exit gating.
- [x] **10.4 — RecoveryRouter:** `workflow/recovery.py` — classifies errors, applies retry/reassign/escalate decisions.
- [x] **11.1 — mas/tools/web.py:** `web_fetch` (httpx + html2text → Markdown) and `web_search` (Tavily primary / DuckDuckGo fallback).
- [x] **11.2 — mas/tools/sandbox.py:** `run_bash` with strict allowlist: grep, find, ls, cat, wc, head, tail, git. No shell=True.
- [x] **11.3 — skills/registry.yaml updated:** `web_fetch` and `run_bash` registered; `web_search` delegated to mas.tools.web.

- [x] **Phase 3.5 — Cyber-Neon Roguelike: Final Polish & Balancing:**
  - Reviewed `src/` for bugs (stubs only; no game logic existed).
  - Wrote `scripts/balance-test.py` — 1000-run Monte Carlo simulation with floor/enemy death analysis and CI-ready balance gate.
  - Wrote `src/entities/enemy.ts` — typed enemy roster + spawn tables validated by simulation.
  - Balance result: **22.4% win rate** (target 15–25%, seed=42). Enforcer attack 12→8, Boss attack 18→10, drop rates raised across all tiers.

---

## Invariants (Do Not Regress)

- Phase 1 snapshot filtering: `ContextStore.snapshot(keys=[...])` must remain in all call sites
- Phase 2 compression gate: `_compress_proposals()` must run after Round 1
- Phase 3 spec deduplication: `self.spec_content` cached at init
- Phase 5 skills injection: `_build_system_prompt()` wraps every agent call
- **ADDITIVE DOCUMENTATION RULE:** `spec.md` and `tasks.md` must only be updated additively.
- CLAUDECODE stripping: `env.pop("CLAUDECODE", None)` in every subprocess call — never skip