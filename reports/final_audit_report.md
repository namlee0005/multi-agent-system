# MAS Optimization Project — Final Audit Report

**Branch:** `feat/automation-upgrade`
**Audit Date:** 2026-03-17
**Auditor:** Architect

---

## Executive Summary

Phases 1–3 and the Skills System (Phase 5) are correctly implemented and verifiable in code. **Phase 4 (SDK Migration + Prompt Caching) is not implemented** — `agents.py` still invokes the LLM via `subprocess.run()` CLI calls. The ~40% caching savings claimed for Phase 4 are unrealized. All three tasks.md corrective actions (mutation bug fix, pre-commit hook, prompt logging) are confirmed implemented.

---

## Phase-by-Phase Verification

### Phase 1 — Snapshot Key Filtering ✅

- `_SNAPSHOT_KEYS_ROUND1`, `_SNAPSHOT_KEYS_ROUND2`, `_SNAPSHOT_KEYS_SYNTHESIS` constants defined in `orchestrator.py:74`
- `ContextStore.snapshot(keys=snapshot_keys)` called at round dispatch and synthesis
- **Estimated savings realized:** ~10–15% per agent call ✓

### Phase 2 — Compression Gate ✅

- `_compress_proposals()` present at `orchestrator.py:492`
- Round 2 agents receive `round1_compressed`, not raw Round 1 proposals
- **Estimated savings realized:** ~60–70% on Round 2 inputs ✓

### Phase 3 — Spec Content Deduplication ✅

- `self.spec_content` cached at `Orchestrator.__init__` (`orchestrator.py:110–114`)
- `FileNotFoundError` raised at construction time
- No per-call `spec.md` reads in `run_agent()` or `run_planner_debate()`
- **Savings realized:** eliminates N file-reads per session ✓

### Phase 4 — SDK Migration + Prompt Caching ❌ NOT IMPLEMENTED

**Finding:** `agents.py` still contains `subprocess.run()` at line 84. No `anthropic` import, no `cache_control: ephemeral` anywhere in the codebase.

The commit message `6a14baf` claims "Replaced Claude/Gemini subprocess calls with native SDKs" — **this is inaccurate**. The code was not changed to use the SDK.

**Impact:** The projected ~40% savings on static prompt blocks is zero. Every agent call incurs full subprocess overhead (process spawn, CLI arg parsing, stdio pipe marshalling) and no prompt caching.

**Risk:** The CLI dependency (`claude` binary) is an external process with no SDK-level retry, streaming, or structured error handling.

### Phase 5 — Skills System ✅

| Check | Result |
|-------|--------|
| All 6 `SKILL.md` files present | ✅ |
| `_load_skills()` at `__init__`, instance dict cache | ✅ |
| `_build_system_prompt()` appends after base prompt | ✅ |
| Mutation bug fixed — `try/finally` restores `original_system_prompt` (`orchestrator.py:351,459`) | ✅ |
| Prompt logging to `logs/prompts/{timestamp}_{agent}.txt` | ✅ |
| `.pre-commit-config.yaml` wiring `lint_skills.py` | ✅ |
| `skills_injected: bool` in session JSON | ✅ |
| No `_shared/` directory (no proven duplication) | ✅ |

---

## Tasks.md Completion Status

The `tasks.md` corrective tasks (Skills System audit) do not use `[x]` checkbox syntax — they are prose entries. All three are confirmed implemented in code:

| Task | Description | Code Evidence |
|------|-------------|---------------|
| Task 1 | Fix mutation bug | `try/finally` at `orchestrator.py:459` ✅ |
| Task 2 | Wire pre-commit hook | `.pre-commit-config.yaml` present ✅ |
| Task 3 | Add prompt file logging | `logs/prompts/` write at `orchestrator.py:354` ✅ |

**Gap:** Tasks 1–3 are not marked complete in `tasks.md` itself. The file should be updated with completion markers per the CLAUDE.md convention.

---

## Realized vs. Projected Token Savings

| Phase | Projected Savings | Realized |
|-------|------------------|----------|
| Phase 1 — Snapshot Filtering | 10–15% per agent call | ✅ Realized |
| Phase 2 — Compression Gate | 60–70% on Round 2 inputs | ✅ Realized |
| Phase 3 — Spec Deduplication | File I/O elimination | ✅ Realized |
| Phase 4 — SDK + Prompt Caching | ~40% on static blocks | ❌ Zero — subprocess still used |
| Phase 5 — Skills System | Quality improvement (not token reduction) | ✅ Deployed |

**Net position:** Phases 1–3 alone deliver significant token reduction on context passing (the dominant cost in multi-round debates). Phase 4 remains the largest single unrealized optimization.

---

## Open Risks

| Risk | Severity | Status |
|------|----------|--------|
| Phase 4 not implemented — subprocess LLM calls, no caching | HIGH | Open |
| tasks.md completion markers missing | LOW | Open |
| `Planner` has no `SKILL.md` — graceful degradation silently skips skills | NEGLIGIBLE | Acceptable by spec |
| `cl100k_base` tokenizer used for Claude models (BPE approximation only) | LOW | Acceptable — within ~5% margin |

---

## Recommendations

1. **Implement Phase 4 for real.** Add `anthropic` SDK to dependencies. Replace `Agent.call_llm()` subprocess logic with `client.messages.create()`. Apply `cache_control: {"type": "ephemeral"}` to the `system` block. This is the highest-ROI remaining task.

2. **Update tasks.md.** Mark Tasks 1–3 as `[x]` per CLAUDE.md convention (`## After Every Task: Mark completed tasks in tasks.md with [x]`).

3. **Add a Phase 4 task entry** to `tasks.md` documenting the gap so it is not silently dropped.