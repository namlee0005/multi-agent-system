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

---

## Backlog

### Phase 6.5 — Gemini Session Pinning (Future, conditional)

If stateless Gemini calls prove insufficient, implement explicit session index tracking via `--list-sessions` parsing. Map Gemini UUID to index.

### Phase 6.6 — Parallelism Recovery (Future, conditional)

If session locks cause measurable serialization overhead, implement `SessionPool` with N=3 pre-warmed sessions per agent.

---

## Invariants (Do Not Regress)

- Phase 1 snapshot filtering: `ContextStore.snapshot(keys=[...])` must remain in all call sites
- Phase 2 compression gate: `_compress_proposals()` must run after Round 1
- Phase 3 spec deduplication: `self.spec_content` cached at init
- Phase 5 skills injection: `_build_system_prompt()` wraps every agent call
- **ADDITIVE DOCUMENTATION RULE:** `spec.md` and `tasks.md` must only be updated additively.
- CLAUDECODE stripping: `env.pop("CLAUDECODE", None)` in every subprocess call — never skip
