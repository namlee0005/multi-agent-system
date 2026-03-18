# MAS Implementation Tasks

## Completed

- [x] Phase 1: Snapshot Key Filtering — `ContextStore.snapshot(keys=[...])` filtering
- [x] Phase 2: Compression Gate — `_compress_proposals()` with `## Summary` extraction
- [x] Phase 3: Spec Content Deduplication — `self.spec_content` cached at init
- [x] Phase 4: SDK Migration + Prompt Caching — *superseded by Phase 6*
- [x] Phase 5: Skills System — per-agent `SKILL.md` injection with token cap enforcement
- [x] Phase 6: CLI Session Persistence — implemented with `SessionStore` and `CLISession`

---

## Active

### Phase 7: Correctness & Safety

**Goal:** Eliminate known failure modes before any new features land. Focus on data races, safe invalidation, and session observability.

- [ ] **7.1 — CLAUDECODE env strip enforcement audit:** Add unit test to verify `env.pop("CLAUDECODE", None)` is present in every subprocess call path.
- [ ] **7.2 — Session invalidation on synthesis completion:** Ensure `SessionStore.invalidate(project_path)` is called unconditionally (via `try/finally`) after synthesis.
- [ ] **7.3 — Gemini stateless enforcement:** Add an assertion to mechanically prevent Gemini agents from passing `--resume` (avoiding unsafe `latest` race).
- [ ] **7.4 — --resume retry contract implementation:** Implement the "retry exactly once without resume" logic if a resumed call returns non-zero.
- [ ] **7.5 — Benchmark gate (BLOCKING):** Measure total token cost of 10 baseline sessions vs 10 resumed sessions. If savings < 5%, re-evaluate SDK path.
- [ ] **7.6 — CLICallResult completeness validation:** Assert that `session_id`, `is_resumed`, and `duration_s` are always populated and logged to `logs/session-{id}.json`.
- [ ] **7.7 — Skills token cap CI enforcement:** Integrate `scripts/lint_skills.py` into a required CI check to block merges violating the 200-token cap.

---

### Phase 8: Hardening & Robustness

**Goal:** Transform MAS into a resilient, production-grade system with deep observability.

- [ ] **8.1 — Structured error taxonomy:** Implement a typed `MASError` hierarchy (SessionError, BinaryNotFoundError, etc.) for better alerting.
- [ ] **8.2 — Session log integrity check:** Validate the previous session closed cleanly before starting a new one; warn on interrupted logs.
- [ ] **8.3 — Skill injection observability:** Surface `skills_injected: true/false` directly in CLI output summaries.
- [ ] **8.4 — Regression test suite:** Full end-to-end flow test with a mock CLI binary to prevent future regressions.

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
