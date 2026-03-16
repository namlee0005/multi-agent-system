# Multi-Agent System (MAS) Specification

## 1. System Architecture

The MAS consists of an Orchestrator and specialized Agents. The Orchestrator manages debate rounds, context, and agent dispatch. Agents produce proposals in parallel via `ThreadPoolExecutor`.

### Orchestration Flow

```
SELECTING → PROPOSING → CHALLENGING → REVIEWING → SYNTHESIZING → DONE
```

- **Parallelism:** Round agents run in parallel via `ThreadPoolExecutor`
- **Persistence:** Every session creates a structured JSON log in `logs/session-{id}.json`
- **Verification:** The Orchestrator must verify file existence and content after completion

---

## 2. Context & Snapshot Filtering (Phase 1)

The `ContextStore.snapshot()` method accepts an optional `keys` parameter. Round agents receive only the context keys relevant to their round — not the full store.

```
Round 1:    keys=["project_description"]
Round 2:    keys=["round1_compressed", "project_description", "errors"]
Synthesis:  keys=["proposals", "challenges", "round1_compressed", "errors"]
```

**Estimated token savings:** ~10–15% per agent call.

---

## 3. Compression Gate (Phase 2)

After Round 1, `_compress_proposals()` extracts `## Summary` blocks (self-authored by agents) into a conflict-preserving compressed summary stored as `round1_compressed`. Round 2 agents receive this compressed form, not raw proposals.

**Fallback chain:** self-authored summary → LLM re-summarization → character truncation.

**Estimated token savings:** ~60–70% on Round 2 inputs.

---

## 4. Spec Content Deduplication (Phase 3)

`spec.md` is read once at `Orchestrator.__init__` and stored as `self.spec_content`. No per-call file reads. `FileNotFoundError` raised at construction time, not at first agent call.

---

## 5. SDK Migration + Prompt Caching (Phase 4)

Replace subprocess-based agent invocation with the Anthropic SDK. Apply `cache_control: ephemeral` to system prompts to cache static blocks across calls.

**Estimated savings:** ~40% on static prompt blocks.

---

## 6. Skills System (Phase 5)

To enhance output quality without polluting the core persona, the system uses a modular **Skill Injection** architecture. Skills are role-specific behavioral constraints loaded once at session start and appended to agent system prompts.

### 6.1 Storage Structure

```
skills/
  Architect/SKILL.md
  BackendDev/SKILL.md
  FrontendDev/SKILL.md
  Security/SKILL.md
  Researcher/SKILL.md
  Skeptic/SKILL.md
  _shared/          ← created only when duplication is empirically proven
```

**Design decisions:**
- One file per agent = granular version control (`git diff skills/Security/SKILL.md`)
- Markdown format = directly embeddable into system prompts without transformation
- No YAML registry or frontmatter parsing — plain Markdown concatenation
- Flat tag subscriptions rejected: moves complexity to Orchestrator tag-resolution logic
- Keyword-based conditional injection rejected: non-deterministic, fragile synonym coverage

### 6.2 Loading

```python
# Orchestrator.__init__
self.agent_skills: dict[str, str] = self._load_skills()
```

`_load_skills()` iterates `self.agent_names`, reads each `skills/{AgentName}/SKILL.md`, returns empty string for missing files (graceful degradation — no error). No `@lru_cache` — the instance dict is the cache.

### 6.3 Injection

```python
def _build_system_prompt(self, agent_name: str, base_prompt: str) -> str:
    skill_content = self.agent_skills.get(agent_name, "")
    if not skill_content.strip():
        return base_prompt
    return f"{base_prompt}\n\n## Your Specialized Skills\n{skill_content}"
```

**Prompt structure per agent call:**
1. Role identity (from `AGENT_PROMPTS[agent_name]`)
2. Specialized Skills (from `skills/{AgentName}/SKILL.md`)
3. Dynamic context (from `ContextStore`, filtered by Phase 1)
4. Task (user request)

Skills are **appended** after the base prompt so role behavioral instructions are not overridden.

### 6.4 Assigned Skills Per Agent

| Agent | Core Skills |
|-------|-------------|
| **Architect** | Service boundaries, tradeoff analysis, Pydantic data models, async/Decimal constraints |
| **BackendDev** | Python async/await, Pydantic v2, path sanitization, integration testing (real deps) |
| **FrontendDev** | TypeScript strict mode, WCAG 2.1 AA, bundle optimization, Zod boundary validation |
| **Security** | OWASP Top 10, threat modeling, secrets hygiene, auth/authz separation, least-privilege |
| **Researcher** | Evidence synthesis, source evaluation, confidence quantification, bias detection |
| **Skeptic** | Assumption surfacing, worst-case analysis, complexity challenge, alternative proposals |

### 6.5 Guardrails

- **Token cap:** Each `SKILL.md` must be ≤200 tokens
- **Enforcement:** `scripts/lint_skills.py` runs as a pre-commit hook; blocks commits that violate the cap
- **Tokenizer:** `tiktoken` with `cl100k_base` encoding (same encoding used by Claude-compatible models)
- **Observability:** Session JSON logs `skills_injected: true/false` per agent call; final assembled prompt logged to `logs/prompts/{timestamp}_{agent}.txt`

### 6.6 Shared Skills

A `skills/_shared/` directory is created **only when the same content appears verbatim in ≥2 agent skill files**. No preemptive shared abstractions. Agents that appear to need the same skill (e.g., SQL optimization) typically need different aspects of it: Architect needs query planner awareness; BackendDev needs parameterized query syntax. These are not the same skill.
