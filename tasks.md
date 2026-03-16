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

## Phase 5: Skills System
**Risk:** Low | **Impact:** Output quality improvement per agent role
**Prerequisite:** None (independent of Phases 1–4; can be implemented in parallel)

### Task 5.1 — Create SKILL.md files for each agent role

**Files to create:**

**`skills/Architect/SKILL.md`**
```markdown
## Architect Skills

- Propose concrete architectures with explicit service boundaries and data flows
- Evaluate monolith vs microservices vs serverless tradeoffs with justification
- Define Pydantic data models and storage patterns before implementation begins
- Flag architectural risks: single points of failure, bottlenecks, tight coupling
- Use `Numeric`/`Decimal` for financial data; never `Float`
- Prefer async/await for all I/O-bound operations
- Bound every design decision to the minimum viable complexity for current requirements
```

**`skills/BackendDev/SKILL.md`**
```markdown
## BackendDev Skills

- Implement Python async/await for all I/O-bound tasks (DB, Redis, external APIs)
- Use Pydantic v2 models for all data validation at system boundaries
- Sanitize file paths; restrict writes to project path to prevent traversal
- Use `Decimal` for monetary values; never `float`
- Apply thread-safe logging with `_log_lock` for shared log file writes
- Prefer explicit error types over bare `Exception` catches
- Write integration tests against real dependencies, not mocks
```

**`skills/FrontendDev/SKILL.md`**
```markdown
## FrontendDev Skills

- Use TypeScript strict mode; no implicit `any`
- Prefer server components over client components in Next.js where possible
- Apply WCAG 2.1 AA accessibility standards to all interactive elements
- Minimize bundle size: code-split by route, lazy-load heavy dependencies
- Co-locate component tests with component files
- Use CSS modules or Tailwind; avoid global style mutations
- Validate all API responses at the boundary with Zod or equivalent
```

**`skills/Security/SKILL.md`**
```markdown
## Security Skills

- Apply OWASP Top 10 checks to all proposed designs
- Mandate secrets in environment variables or secret managers; never hardcoded
- Require auth/authz review on every endpoint: authentication + authorization separate
- Flag SQL injection, XSS, CSRF, and path traversal risks explicitly
- Propose threat model: identify assets, threats, mitigations before implementation
- Enforce least-privilege: services request only permissions they need
- Require audit logging for all privileged operations
```

**`skills/Researcher/SKILL.md`**
```markdown
## Researcher Skills

- Synthesize evidence from multiple sources before forming conclusions
- Distinguish primary sources from secondary; flag single-source claims
- Quantify uncertainty: state confidence levels and evidence gaps explicitly
- Structure findings: context → evidence → conclusion → open questions
- Detect and name cognitive biases in proposed approaches
- Prefer reproducible benchmarks over anecdotal performance claims
- Flag when a claim requires empirical validation before implementation
```

**`skills/Skeptic/SKILL.md`**
```markdown
## Skeptic Skills

- Surface unstated assumptions in every proposal before accepting them
- Apply worst-case analysis: what breaks at 10x scale, under network partition, at peak load
- Identify logical fallacies: false dichotomy, appeal to authority, premature optimization
- Challenge complexity: ask "what is the simplest design that satisfies the requirement?"
- Flag coupling: identify hidden dependencies between proposed components
- Require evidence for performance or reliability claims
- Propose at least one alternative approach to every recommendation
```

**Acceptance criteria:**
- All 6 SKILL.md files exist at `skills/{AgentName}/SKILL.md`
- Each file is ≤200 tokens (verified by Task 5.4 lint script)
- Content is actionable and role-specific — not generic best practices

---

### Task 5.2 — Implement `_load_skills()` on `Orchestrator`

**File:** `orchestrator.py`
**Target:** `__init__` method, after `self.spec_content` assignment

**Add to `__init__`:**
```python
self.agent_skills: dict[str, str] = self._load_skills()
```

**New method:**
```python
def _load_skills(self) -> dict[str, str]:
    """
    Load SKILL.md files for all known agent roles.

    Looks for skills/{AgentName}/SKILL.md relative to the project root.
    Missing files produce an empty string (graceful degradation — no error).

    Returns:
        dict[str, str]: Mapping of agent_name → skill content (may be empty string).
    """
    skills: dict[str, str] = {}
    skills_root = Path(self.project_path) / "skills"
    for agent_name in self.agent_names:
        skill_path = skills_root / agent_name / "SKILL.md"
        if skill_path.exists():
            skills[agent_name] = skill_path.read_text(encoding="utf-8")
        else:
            skills[agent_name] = ""
    return skills
```

**Note:** No `@lru_cache` — the instance dict `self.agent_skills` *is* the cache.
`@lru_cache` on a module-level function bleeds cache state between test runs and is redundant here.

**Acceptance criteria:**
- `_load_skills()` called exactly once per `Orchestrator` instance
- Missing SKILL.md → empty string in dict; no `FileNotFoundError` raised
- All agents in `self.agent_names` have a key in returned dict

---

### Task 5.3 — Inject skills into system prompts via `_build_system_prompt()`

**File:** `orchestrator.py`
**Target:** Wherever agent system prompts are assembled (search for `system_prompt` construction in `_call_agent`)

**Add or modify `_build_system_prompt`:**
```python
def _build_system_prompt(self, agent_name: str, base_prompt: str) -> str:
    """
    Append agent-specific skills to the base system prompt.

    Skills are appended after role identity to avoid overriding behavioral instructions.

    Args:
        agent_name: Name matching a key in self.agent_skills.
        base_prompt: The role's base system prompt string.

    Returns:
        str: base_prompt + skills section, or base_prompt if no skills defined.
    """
    skill_content = self.agent_skills.get(agent_name, "")
    if not skill_content.strip():
        return base_prompt
    return f"{base_prompt}\n\n## Your Specialized Skills\n{skill_content}"
```

**Wire into `_call_agent`:**
```python
# Before:
system_prompt = AGENT_PROMPTS[agent_name]

# After:
system_prompt = self._build_system_prompt(agent_name, AGENT_PROMPTS[agent_name])
```

**Acceptance criteria:**
- Skills appended after base prompt, not prepended
- Agents with no SKILL.md receive unmodified base prompt
- System prompt structure: `[role identity] → [behavioral instructions] → [skills]`
- Session JSON logs include `skills_injected: true/false` per agent call

---

### Task 5.4 — CI lint script to enforce SKILL.md token cap

**File:** `scripts/lint_skills.py`

**Implementation:**
```python
#!/usr/bin/env python3
"""Enforce ≤200-token cap on all SKILL.md files. Exit non-zero on violation."""
import sys
from pathlib import Path

import tiktoken

MAX_TOKENS = 200
enc = tiktoken.get_encoding("cl100k_base")
violations = []

for skill_file in sorted(Path("skills").rglob("SKILL.md")):
    tokens = len(enc.encode(skill_file.read_text(encoding="utf-8")))
    if tokens > MAX_TOKENS:
        violations.append(f"  {skill_file}: {tokens} tokens (max {MAX_TOKENS})")

if violations:
    print("SKILL.md token cap violations:")
    print("\n".join(violations))
    sys.exit(1)

print(f"OK: all SKILL.md files within {MAX_TOKENS}-token cap")
```

**Wire into pre-commit (`.pre-commit-config.yaml` or equivalent):**
```yaml
- repo: local
  hooks:
    - id: lint-skills
      name: Enforce SKILL.md token cap
      entry: python scripts/lint_skills.py
      language: python
      additional_dependencies: [tiktoken]
      pass_filenames: false
```

**Acceptance criteria:**
- Script exits 0 when all SKILL.md files are within cap
- Script exits 1 and names violating files when any exceed 200 tokens
- Runs automatically on `git commit` when pre-commit hook is installed
- `tiktoken` added to dev dependencies

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

Task 5.1 → Task 5.2 → Task 5.3 → Task 5.4
  (no deps)  (needs 5.1)  (needs 5.2)   (needs 5.1, CI wiring)
  [Phase 5 is fully independent — can run in parallel with Phases 1–4]
```

---

## Verification Checklist

```
[ ] Phase 1: session log shows ≤3 keys in Round 1 context_store per agent
[ ] Phase 1: Round 2 agents show "round1_compressed" key, not raw proposals dict
[ ] Phase 2: session JSON contains compression_stats.method field
[ ] Phase 2: CONFLICT lines present when agent proposals diverge
[ ] Phase 3: "spec.md read" log line appears exactly once per session
[ ] Phase 4: cache_read_input_tokens > 0 on second session with same system prompt
[ ] Phase 5: skills/*/SKILL.md files exist and pass lint_skills.py (≤200 tokens)
[ ] Phase 5: session JSON contains skills_injected field per agent call
[ ] Phase 5: agents with no SKILL.md receive unmodified base prompt (no KeyError)
[ ] Phase 5: pre-commit hook blocks commits that violate token cap
[ ] All phases: debate quality unchanged (proposal length, synthesis coherence)
```