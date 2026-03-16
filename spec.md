# Multi-Agent System (MAS) Optimization Specification

## Executive Summary

The Multi-Agent System suffers from O(n²) token growth caused by three compounding issues
in `orchestrator.py`: unconditional full-store snapshot injection on every agent call,
repeated `spec.md` file reads per invocation, and no inter-round compression. The fix is
a four-phase incremental hardening plan delivering an estimated 60–80% token reduction
across a full session. Code stubs are out of scope — the stability-tracking overhead
exceeds the benefit. SDK migration is Phase 4 (not Phase 1) because Phases 1–3 deliver
the majority of savings with zero regression risk and require no SDK instrumentation to
verify.

## Recommended Tech Stack

| Component | Choice | Reasoning |
|-----------|--------|-----------|
| Context filtering | `ContextStore.snapshot(keys=)` | Zero-dep, reversible, backward-compatible |
| Compression | Self-compression per agent + cheapest model fallback | Avoids cross-agent bias; fallback is char truncation |
| Spec loading | `self.spec_content` at `__init__` | Eliminates N repeated file reads per session |
| SDK (Phase 4) | `anthropic` Python SDK | Unlocks `cache_control`, structured usage stats, eliminates 300ms subprocess overhead |
| Gemini SDK (Phase 4b) | `google-generativeai` | Parallel migration, usage tracking parity |

Code stubs via tree-sitter or CTags are **dropped** — no stability oracle exists in the
current codebase, and snapshot key filtering achieves selective injection without
hallucination risk from hidden implementations.

## Architecture Overview

```
Session Start
  └─ Orchestrator.__init__()
       └─ load spec.md ONCE → self.spec_content           [Phase 3]

Round 1 Dispatch (parallel via ThreadPoolExecutor)
  └─ _call_agent(round="round1")
       └─ snapshot(keys=["project_description"])           [Phase 1]
       └─ agent appends "## Summary\n- bullet..." block    [Phase 2]

_compress_proposals()  — runs once after Round 1           [Phase 2]
  └─ collects per-agent Summary blocks
  └─ stores context["round1_compressed"]
  └─ fallback: 500-char truncation per agent if model call fails/times out

Round 2 Dispatch (parallel)
  └─ _call_agent(round="round2")
       └─ snapshot(keys=["round1_compressed",              [Phase 1]
                          "project_description", "errors"])

Synthesis
  └─ _synthesize()
       └─ snapshot(keys=["proposals", "challenges",        [Phase 1]
                          "round1_compressed", "errors"])

Phase 4 (deferred — prerequisite: Phases 1–3 verified):
  agents.py respond() → anthropic.messages.create()
    system_prompt → cache_control: {"type": "ephemeral"}
    returns (text, usage_stats) with cache_read_input_tokens
```

### Key Snapshot Key Map

```python
ROUND_SNAPSHOT_KEYS = {
    "round1":    ["project_description"],
    "round2":    ["round1_compressed", "project_description", "errors"],
    "synthesis": ["proposals", "challenges", "round1_compressed", "errors"],
}
```

### Estimated Token Savings Per Phase

| Phase | Change | Token Impact |
|-------|--------|-------------|
| 1 | Snapshot key filtering | ~10–15% per agent call |
| 2 | Compression gate | ~60–70% on Round 2 inputs |
| 3 | Spec deduplication | Eliminates N file reads |
| 4 | SDK + cache_control | ~40% on static blocks |