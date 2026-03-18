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

## 5. CLI Session Persistence (Phase 6)

Replaces Phase 4 (SDK + prompt caching). LLM invocation uses `subprocess.run()` with `--resume <session-id>` to achieve server-side context continuity across debate rounds without persistent process management.

### 5.1 Session Key Model

Session key: `(backend, agent_name, project_path)` — one session per agent role per project.

- Round 2 Architect resumes Round 1 Architect's session (desired continuity).
- Architect never shares a session with Skeptic (correct isolation).
- Sessions are invalidated via `SessionStore.invalidate(project_path)` after synthesis to prevent cross-project context bleed.

### 5.2 Claude Session Management

Claude CLI exposes `--session-id <uuid>` and `--resume <uuid>`. The UUID is pre-generated at `Orchestrator.__init__` — no stdout extraction required.

```
First call:      claude --print --session-id <uuid> --output-format json ...
Subsequent:      claude --print --resume <uuid> --output-format json ...
Extraction fail: session_id=None → stateless fallback (logged warning, not exception)
```

### 5.3 Gemini Session Management

Gemini CLI `--resume latest` is **unsafe under `ThreadPoolExecutor`** — concurrent threads racing to resume "latest" serialize and may cross-contaminate sessions. Gemini runs **stateless by default**. Index-pinning via `--list-sessions` output parsing is deferred to Phase 6.5.

### 5.4 CLAUDECODE Environment Constraint

The MAS orchestrator runs inside a Claude Code session. The `CLAUDECODE` env var causes Claude CLI to refuse to launch nested sessions. All subprocess calls must strip this variable:

```python
env = os.environ.copy()
env.pop("CLAUDECODE", None)
subprocess.run([...], env=env, ...)
```

This is enforced in `CLISession.call()`, not in a wrapper. It is non-negotiable.

### 5.5 Binary Validation

CLI binary availability is validated at `Orchestrator.__init__` via `shutil.which()`. Missing binaries raise `RuntimeError` immediately — not on first agent call 30 seconds into a session.

### 5.6 Failure Mode Contract

| Failure | Response |
|---|---|
| Binary not found at init | `RuntimeError` — fail fast |
| Session ID extraction failure | `session_id=None` → stateless fallback, log warning |
| `--resume` returns non-zero | Retry once without `--resume`; clear session_id |
| Gemini race condition | Stateless by design; no retry needed |

### 5.7 Observability

`CLICallResult` includes `session_id: str | None`, `is_resumed: bool`, `duration_s: float`. Both fields are logged in `logs/session-{id}.json` per agent call. Operators can verify `--resume` is actually being used by inspecting `is_resumed` in session logs.

### 5.8 Estimated Token Savings

| Mechanism | Savings |
|---|---|
| Phase 1 snapshot filtering | ~10–15% per agent call |
| Phase 2 compression gate | ~60–70% on Round 2 inputs |
| Phase 6 `--resume` context continuity | ~20–40% on repeated calls to same agent |
| Prompt caching (Phase 4) | **Eliminated** — not available via CLI |

Net position vs Phase 4 (SDK + caching): requires measurement. Token budget comparison is an open prerequisite before declaring net win.

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

A `skills/_shared/` directory is created **only when the same content appears verbatim in ≥2 agent skill files**. No preemptive shared abstractions.

---

## 7. CLI Migration Rationale

Phase 4 (SDK + prompt caching) was implemented and then reverted. The active codebase (`agents.py`) uses `subprocess.run()` — CLI is the live execution path. Phase 6 formalizes this by adding session persistence on top of the existing CLI path.

**Why CLI over SDK:**
- No third-party SDK dependency
- `subprocess.run()` works for any CLI-exposed model (local, cloud, future)
- Session semantics (`--resume`) are a first-class CLI feature

**What is lost vs Phase 4:**
- `cache_control: ephemeral` prompt caching (~40% savings on static blocks) is not available via CLI

**Decision:** Accept the caching regression. Measure the `--resume` token savings in Phase 6 benchmarks. If net token cost increases materially, re-evaluate SDK path as a feature flag.