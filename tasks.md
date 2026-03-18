# MAS Implementation Tasks

## Completed

- [x] Phase 1: Snapshot Key Filtering — `ContextStore.snapshot(keys=[...])` filtering
- [x] Phase 2: Compression Gate — `_compress_proposals()` with `## Summary` extraction
- [x] Phase 3: Spec Content Deduplication — `self.spec_content` cached at init
- [x] Phase 4: SDK Migration + Prompt Caching — *superseded by Phase 6*
- [x] Phase 5: Skills System — per-agent `SKILL.md` injection with token cap enforcement
- [x] Phase 6: CLI Session Persistence — implemented with `SessionStore` and `CLISession`

---

## Backlog

### Phase 6.5 — Gemini Session Pinning (Future, conditional)

If stateless Gemini calls prove insufficient (context re-send cost measured and significant), implement explicit session index tracking via `--list-sessions` output parsing. Map Gemini UUID (from JSON response) to index. Use per-agent index, not `--resume latest`.

**Prerequisite:** Observe stateless Gemini in production; measure token cost delta.

### Phase 6.6 — Parallelism Recovery (Future, conditional)

If per-agent session locks cause measurable serialization overhead in benchmarks, implement `SessionPool` with N=3 pre-warmed sessions per `(backend, agent_name)`. Agents acquire from pool via `queue.Queue`.

**Prerequisite:** Benchmark Phase 6.3 baseline (with `--resume`) vs Phase 4 baseline (SDK); confirm regression exists.

### Phase 6.7 — Token Budget Measurement

After Phase 6.3 ships: measure actual token savings from `--resume` vs lost prompt caching savings from Phase 4. If net token cost is higher with CLI, re-evaluate SDK path as opt-in mode via `runner: "sdk" | "cli"` config flag.

---

## Invariants (Do Not Regress)

- Phase 1 snapshot filtering: `ContextStore.snapshot(keys=[...])` must remain in all call sites
- Phase 2 compression gate: `_compress_proposals()` must run after Round 1; CLI session does not eliminate this (safety valve for long sessions)
- Phase 3 spec deduplication: `self.spec_content` cached at init; no per-call file reads
- Phase 5 skills injection: `_build_system_prompt()` wraps every agent call; CLI backend is transparent to this layer
- CLAUDECODE stripping: `env.pop("CLAUDECODE", None)` in every subprocess call — never skip
