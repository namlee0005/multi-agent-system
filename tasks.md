# MAS Optimization — Implementation Tasks

> Synthesized 2026-03-16 — Final plan post-debate.
> Protocol: CLAUDE.md §Task Protocol — full signatures, explicit file paths, retry limits apply.

---

## Phase 1: Snapshot Key Filtering
**Risk:** Minimal | **Estimated Token Savings:** ~10–15% per agent call

### Task 1.1 — Add `keys` parameter to `ContextStore.snapshot()`

**File:** `context_store.py`
**Target line:** ~67 (existing `snapshot()` method)

**Signature:**
```python
def snapshot(self, keys: list[str] | None = None) -> dict:
    """
    Return a shallow copy of the context store.

    Args:
        keys: If provided, return only the specified keys (missing keys are
              silently skipped). If None, return the full store (preserves
              existing behavior).

    Returns:
        dict: Filtered or full snapshot. Lists are shallow-copied to prevent mutation.
    """
    with self._lock:
        source = (
            self._store
            if keys is None
            else {k: self._store[k] for k in keys if k in self._store}
        )
        return {
            k: list(v) if isinstance(v, list) else v
            for k, v in source.items()
        }
```

**Acceptance criteria:**
- `snapshot()` with no args returns identical output to current behavior
- `snapshot(keys=["x"])` returns only key `x`; missing keys do not raise
- Thread-safety: `_lock` still wraps the full operation

---

### Task 1.2 — Update `_call_agent` and `_synthesize` snapshot call sites

**File:** `orchestrator.py`
**Target lines:** ~286 (inside `_call_agent`), ~604 (inside `_synthesize`)

**Add module-level constant:**
```python
ROUND_SNAPSHOT_KEYS: dict[str, list[str]] = {
    "round1":    ["project_description"],
    "round2":    ["round1_compressed", "project_description", "errors"],
    "synthesis": ["proposals", "challenges", "round1_compressed", "errors"],
}
```

**Replace at line ~286 inside `_call_agent`:**
```python
# Before:
ctx["context_store"] = self.context.snapshot()

# After:
round_key = ctx.get("round", "round1")
ctx["context_store"] = self.context.snapshot(
    keys=ROUND_SNAPSHOT_KEYS.get(round_key)
)
```

**Replace at line ~604 inside `_synthesize`:**
```python
ctx["context_store"] = self.context.snapshot(
    keys=ROUND_SNAPSHOT_KEYS["synthesis"]
)
```

**Acceptance criteria:**
- Round 1 agents do not receive Round 2 or challenge data
- Synthesis receives proposals, challenges, errors — nothing else
- Existing session JSON logs still serialize correctly

---

## Phase 2: Compression Gate
**Risk:** Low | **Estimated Token Savings:** ~60–70% on Round 2 inputs

### Task 2.1 — Agent self-compression protocol

**Scope:** System prompt update for all agent roles

Each agent's system prompt must include the following footer instruction:

```
At the end of your response, append a section exactly as follows:

## Summary
- [bullet: your most important recommendation]
- [bullet: key constraint or risk you identified]
- [bullet: any explicit disagreement with another agent's position, if applicable]

Maximum 4 bullets. This section is used for inter-round compression.
```

**Acceptance criteria:**
- All agent responses in Round 1 contain a `## Summary` section
- Bullets are self-authored — no cross-agent reinterpretation

---

### Task 2.2 — Implement `_compress_proposals()` on `Orchestrator`

**File:** `orchestrator.py`
**Insert after:** existing `_synthesize` method

**Signature:**
```python
def _compress_proposals(
    self,
    proposals: dict[str, str],
    *,
    model: str = "gemini-flash",
    max_bullets_per_agent: int = 4,
) -> str:
    """
    Compress Round 1 proposals into a conflict-preserving summary.

    Extracts "## Summary" blocks from each agent's self-compressed response.
    Falls back to cheapest-model summarization if Summary blocks are missing.
    Falls back to character truncation if model call fails or exceeds 10s.

    Args:
        proposals: Mapping of agent_name → full proposal text.
        model: Backend model key for fallback summarization.
        max_bullets_per_agent: Maximum bullets to retain per agent.

    Returns:
        str: Compressed multi-agent summary stored in context as
             "round1_compressed". Format: Markdown bullet list per agent.

    Side effects:
        - Calls self.context.set("round1_compressed", result)
        - Logs to session JSON under "compression_stats":
          {input_tokens, output_tokens, method: "self"|"llm"|"fallback"}

    Raises:
        Never — all failures fall back to truncation.
    """
```

**Summary extraction logic:**
```python
import re

def _extract_summary_block(text: str) -> str | None:
    """Extract '## Summary' section from agent response, if present."""
    match = re.search(r"##\s+Summary\s*\n((?:[-*].+\n?)+)", text, re.IGNORECASE)
    return match.group(0).strip() if match else None
```

**Fallback compression prompt (module-level constant):**
```python
COMPRESSION_PROMPT = """\
Compress these Round 1 debate proposals. Rules:
1. For each agent, emit at most {max_bullets} bullet points.
2. PRESERVE explicit disagreements: "CONFLICT: [AgentA] says X; [AgentB] says Y."
3. Do not resolve conflicts. Do not editorialize.
4. Format: ## [AgentName]\n- bullet\n- bullet

Proposals:
{proposals_block}
"""
```

**Character truncation fallback:**
```python
TRUNCATION_FALLBACK_CHARS = 500

def _fallback_compress(proposals: dict[str, str]) -> str:
    return "\n\n".join(
        f"## {name}\n{text[:TRUNCATION_FALLBACK_CHARS]}..."
        for name, text in proposals.items()
    )
```

**Acceptance criteria:**
- Self-authored `## Summary` blocks are preferred over LLM re-summarization
- LLM fallback used only when Summary blocks are absent from >50% of proposals
- Character truncation fallback used if model call raises or times out (10s)
- `compression_stats.method` reflects which path was taken: `"self"`, `"llm"`, or `"fallback"`
- CONFLICT lines present in output when proposals diverge

---

### Task 2.3 — Wire compression gate into `run_planner_debate()`

**File:** `orchestrator.py`
**Target:** Inside `run_planner_debate()`, after Round 1 agent dispatch loop

```python
# After Round 1 completes:
round1_proposals = {
    name: self.context.get(f"{name}_proposal", "")
    for name in self.agent_names
}
self._compress_proposals(round1_proposals)
# Round 2 dispatch follows — _call_agent injects "round1_compressed"
```

**Acceptance criteria:**
- `_compress_proposals` called exactly once per session
- Round 2 agents receive `round1_compressed`, not raw `proposals` dict
- Order: compress → Round 2 dispatch (never parallel)

---

## Phase 3: Spec Content Deduplication
**Risk:** Zero | **Estimated Impact:** Eliminates N repeated file reads per session

### Task 3.1 — Cache `spec.md` at `Orchestrator.__init__`

**File:** `orchestrator.py`
**Target:** `__init__` method

**Add to `__init__`:**
```python
spec_path = Path(self.project_path) / "spec.md"
if not spec_path.exists():
    raise FileNotFoundError(
        f"spec.md not found at {spec_path}. "
        "Cannot initialize Orchestrator without a project spec."
    )
self.spec_content: str = spec_path.read_text(encoding="utf-8")
```

**Remove from `run_agent()` (~line 690–695):**
```python
# DELETE:
with open(os.path.join(self.project_path, "spec.md")) as f:
    spec_content = f.read()
```

**Replace with:**
```python
spec_content = self.spec_content  # loaded at __init__
```

**Also add to `run_planner_debate()`** (currently does not load spec at all):
```python
spec_content = self.spec_content
```

**Acceptance criteria:**
- `spec.md` read exactly once per `Orchestrator` instance
- `FileNotFoundError` at construction time, not at first agent call
- Both `run_agent()` and `run_planner_debate()` use `self.spec_content`

---

## Phase 4: SDK Migration + Prompt Caching
**Risk:** Medium | **Estimated Savings:** ~40% on static blocks
**Prerequisite:** Phases 1–3 complete and verified in production session logs

### Task 4.1 — Replace Claude subprocess with Anthropic SDK

**File:** `agents.py`
**Target lines:** ~56–117 (subprocess-based `respond()`)

**New signature:**
```python
import anthropic

def respond(
    self,
    prompt: str,
    *,
    system_prompt: str,
    cache_system_prompt: bool = True,
) -> tuple[str, dict]:
    """
    Send prompt to Claude via Anthropic SDK.

    Args:
        prompt: User-turn content.
        system_prompt: System prompt. Wrapped with cache_control if
                       cache_system_prompt=True.
        cache_system_prompt: Apply ephemeral cache_control to system prompt.
                             Default True. Set False for one-off dynamic prompts.

    Returns:
        tuple[str, dict]: (response_text, usage_stats)
        usage_stats keys: input_tokens, output_tokens,
                          cache_creation_input_tokens, cache_read_input_tokens

    Raises:
        anthropic.APIError: Re-raised after logging.
    """
```

**Cache control structure:**
```python
system_block = [
    {
        "type": "text",
        "text": system_prompt,
        **({"cache_control": {"type": "ephemeral"}} if cache_system_prompt else {}),
    }
]
```

**Acceptance criteria:**
- No subprocess calls remain for Claude-backend agents
- `usage_stats` written to session JSON per agent call
- `cache_read_input_tokens > 0` in logs on second+ call with identical system prompt
- Gemini agents continue using existing path until Phase 4b

### Task 4.2 — Gemini SDK migration (Phase 4b)

**File:** `agents.py`
**Scope:** Replace `gemini --yolo` subprocess with `google-generativeai` SDK
**Note:** Usage tracking only — Gemini context caching API differs from Anthropic's
         and requires separate design decision before implementation.

---

## Dropped: Code Stubs

Code stub generation via tree-sitter, CTags, or stdlib `ast` is **removed from scope**.

**Rationale:** No file-stability oracle exists in the current codebase. "Stable = no
commits in 7 days" requires `git log` per file on every session start. Snapshot key
filtering (Phase 1) achieves selective injection without hallucination risk from hidden
implementations. Revisit only if Phase 1–3 savings prove insufficient at scale.

---

## Implementation Order

```
Task 1.1 → Task 1.2 → Task 3.1 → Task 2.1 → Task 2.2 → Task 2.3 → Task 4.1 → Task 4.2
  (no deps)  (needs 1.1) (independent) (independent) (needs 2.1) (needs 2.2) (needs all) (needs 4.1)
```

Phases 1 and 3 can be implemented in parallel. Phase 2 requires Phase 1 (snapshot keys
must exist before compression gate reads them). Phase 4 requires all prior phases verified.

---

## Verification Checklist

```
[ ] Phase 1: session log shows ≤3 keys in Round 1 context_store per agent
[ ] Phase 1: Round 2 agents show "round1_compressed" key, not raw proposals dict
[ ] Phase 2: session JSON contains compression_stats.method field
[ ] Phase 2: CONFLICT lines present when agent proposals diverge
[ ] Phase 3: "spec.md read" log line appears exactly once per session
[ ] Phase 4: cache_read_input_tokens > 0 on second session with same system prompt
[ ] All phases: debate quality unchanged (proposal length, synthesis coherence)
```