# Multi-Agent System (MAS) — Comprehensive Technical Reference

> **Version:** Phase 8 Complete | **Date:** 2026-03-18

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Full Pipeline Workflow](#2-full-pipeline-workflow)
3. [Memory & Context Optimizations](#3-memory--context-optimizations)
4. [Phase 6 CLI Session Persistence](#4-phase-6-cli-session-persistence)
5. [Phase 7 & 8 Hardening](#5-phase-7--8-hardening)
6. [Developer Guide](#6-developer-guide)

---

## 1. System Architecture

### 1.1 Component Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (CLI Entry)                      │
│  Argument parsing → Mode dispatch → Report generation           │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                    Orchestrator (orchestrator.py)               │
│  Session mgmt · Agent dispatch · Debate flow · Artifact gate    │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐│
│  │ ContextStore │  │ SessionStore │  │     RateLimiter        ││
│  │ (shared mem) │  │(.mas/sess.)  │  │ (per-backend tokens)   ││
│  └──────────────┘  └──────────────┘  └────────────────────────┘│
└──────┬────────────────────────────────────────┬─────────────────┘
       │                                        │
       ▼                                        ▼
┌──────────────┐                     ┌──────────────────────────┐
│  Planner     │                     │  Specialist Agents        │
│  (agent)     │                     │  researcher, architect,   │
│  Selection + │                     │  backend_dev, frontend,   │
│  Synthesis   │                     │  devops, security,        │
└──────────────┘                     │  skeptic, code_reviewer  │
                                     └──────────────────────────┘
                                                │
                                     ┌──────────▼───────────────┐
                                     │  CLISession              │
                                     │  (backends/cli_session)  │
                                     │  subprocess + resume     │
                                     └──────────────────────────┘
```

### 1.2 Orchestrator (`orchestrator.py`)

The `Orchestrator` is the central engine. It is instantiated once per `main.py` invocation and owns the full debate lifecycle.

**Construction invariants** (all enforced at `__init__`, not lazily):
- `shutil.which()` validates every configured CLI binary → `BinaryNotFoundError` if missing
- `spec.md` is read once and cached as `self.spec_content` → `FileNotFoundError` at construction, not at first agent call
- All `skills/{AgentName}/SKILL.md` files are loaded into `self.agent_skills: dict[str, str]`
- Previous session log integrity is checked → warning logged if `end_time` absent

**Key attributes:**

| Attribute | Type | Purpose |
|-----------|------|---------|
| `config` | `dict` | Parsed `config.yaml` |
| `project_path` | `str \| None` | Target directory for file writes |
| `skip_review` | `bool` | Bypass `CodeReviewer` gate |
| `spec_content` | `str` | Cached `spec.md` contents |
| `session_store` | `SessionStore` | Cross-round session ID persistence |
| `session_id` | `str` | UUID for current session's JSON log |
| `context` | `ContextStore` | Shared mutable debate state |
| `agent_skills` | `dict[str, str]` | Per-agent SKILL.md text |
| `session_log` | `dict` | In-memory structured log, flushed at end |

### 1.3 ContextStore (`context_store.py`)

Thread-safe, RLock-protected shared state across all parallel agents.

**Storage model:**

```python
LIST_KEYS = {"proposals", "challenges", "artifacts", "errors"}
# All other keys are scalar (str, dict, etc.)
```

**API:**

```python
store.set("project_description", "Build a Todo CLI")
store.get("project_description")                      # → str
store.append("proposals", {"agent": "...", "text": "..."})
store.get_list("proposals")                           # → list copy (safe)
store.snapshot(keys=["proposals", "errors"])          # → filtered dict copy
```

**`snapshot(keys)` semantics:**
- List buckets are shallow-copied into the snapshot
- Scalar values are referenced (they are strings — effectively immutable)
- The caller holds no lock after `snapshot()` returns; the store continues to accept writes from other threads without blocking

### 1.4 Agents (`agents.py`)

Each agent is an `Agent` dataclass:

```python
@dataclass
class Agent:
    name: str
    role: str
    system_prompt: str
    project_path: Optional[str]
    backend: str          # "claude" | "gemini"
    model: str
    temperature: float
    session_store: Optional[SessionStore]
```

**Agent roster and temperatures:**

| Agent | Role | Temperature | Notes |
|-------|------|-------------|-------|
| `planner` | Moderator/synthesizer | 0.5 | JSON output for selection |
| `researcher` | Evidence synthesis | 0.7 | Cites real projects |
| `architect` | System design | 0.7 | Pydantic models, boundaries |
| `backend_dev` | Backend implementation | 0.8 | Language/DB/framework |
| `frontend_dev` | UI/UX | 0.8 | TS, WCAG, bundle |
| `devops` | Infrastructure | 0.7 | CI/CD, cost, scaling |
| `security` | Threat modeling | 0.6 | Conservative by design |
| `skeptic` | Devil's advocate | 0.9 | Surfaces hidden assumptions |
| `code_reviewer` | Artifact gate | 0.3 | JSON output: PASS/WARN/FAIL |

**`respond()` call path:**

```
Agent.respond()
  └─ build_prompt()          # inject context blocks
  └─ call_llm()              # acquire rate limit token
      └─ CLISession.call()   # subprocess + session resume
  └─ extract <write_file>    # parse and write files to disk
  └─ sanitize paths          # realpath + startswith check
  └─ return stripped text
```

**File write safety:**
Every path extracted from a `<write_file path="...">` tag is resolved with `Path(path).resolve()` and validated to start with the configured `project_path`. Writes outside the project root are silently dropped and logged as errors.

### 1.5 CLISession (`backends/cli_session.py`)

Low-level subprocess wrapper with session resumption.

```python
class CLISession:
    backend: str
    agent_name: str
    project_path: str
    command: str       # resolved binary path
    model: str
    session_store: SessionStore
    timeout: int       # default 600s
```

**`call()` flow:**

```
_get_env()                    # strip CLAUDECODE
get session_id from store
  ├─ Claude: session exists?
  │    Yes → --resume <id>
  │    No  → --session-id <new-uuid>
  └─ Gemini: always stateless (no resume args)
subprocess.run(cmd, env=env, timeout=timeout)
  ├─ Non-zero returncode?
  │    If --resume was used → retry once without --resume (stateless fallback)
  │    Else → raise BackendCallError
  └─ Success → parse JSON stdout
      ├─ Extract result text
      ├─ Extract session_id (persist to store)
      └─ Sum tokens: input + cache_read + cache_creation
Return CLICallResult(content, session_id, is_resumed, duration_s, tokens)
```

### 1.6 SessionStore (`backends/session_store.py`)

Persists session UUIDs to `.mas/sessions.json`.

**Key model:** `"{backend}:{agent_name}:{abs_project_path}"`

This ensures:
- Round 2 Architect resumes Round 1 Architect's session ✓
- Architect never shares a session with Skeptic ✓
- Sessions are project-scoped (different projects → different sessions) ✓

**Invalidation:** Called by `Orchestrator` after synthesis completes:

```python
session_store.invalidate(project_path)  # clears all keys for this project
```

Prevents stale context from bleeding into a future unrelated session.

### 1.7 RateLimiter (`rate_limiter.py`)

Token-bucket rate limiter instantiated as a module-level singleton in `agents.py`.

```python
_rate_limiter = RateLimiter(limits_rpm={"claude": 10, "gemini": 15})
```

Each `Agent.call_llm()` calls `_rate_limiter.acquire(backend)` before dispatching to `CLISession`. Unknown backends default to 10 RPM. The bucket refills at `rpm / 60.0` tokens/second.

---

## 2. Full Pipeline Workflow

### 2.1 State Machine

```
SELECTING → PROPOSING → CHALLENGING → REVIEWING → SYNTHESIZING → DONE
```

### 2.2 Detailed Flow

```
main() parses args
  └─ Orchestrator.__init__()
      ├─ Binary validation (fail-fast)
      ├─ spec.md cache
      ├─ Skills load
      └─ Session integrity check

run_planner_debate(project_description)
  │
  ├─ [SELECTING]
  │   _select_agents()
  │     └─ Planner called with project_description
  │     └─ Parse {"selected_agents": [...]} from JSON response
  │     └─ Fallback: hardcoded defaults if JSON parse fails
  │     └─ Enforce min=3, max=5
  │
  ├─ [PROPOSING — Round 1]
  │   _run_round(selected_agents, round_num=1, is_challenge=False)
  │     └─ ThreadPoolExecutor — all agents run in parallel
  │     └─ For each agent:
  │         _call_agent(key, request, ctx, snapshot_keys=ROUND1_KEYS)
  │           ├─ Skills injection: wrap system_prompt if SKILL.md exists
  │           ├─ LLM call (with retry loop, max 3 attempts)
  │           ├─ validate_response() — length, JSON if expected, tag integrity
  │           ├─ If <write_file> detected: _review_artifact() via CodeReviewer
  │           │     └─ Parse {"status": "PASS"|"WARN"|"FAIL", "issues": [], ...}
  │           │     └─ FAIL → feedback → retry (counts against 3-attempt budget)
  │           └─ Log to session JSON
  │
  ├─ [COMPRESSION]
  │   _compress_proposals()
  │     ├─ Extract "## Summary" blocks (self-authored by agents)
  │     ├─ Fallback: Planner re-summarization via LLM
  │     ├─ Fallback: character truncation
  │     └─ Store as context["round1_compressed"]
  │
  ├─ [CHALLENGING — Round 2]
  │   _run_round(selected_agents, round_num=2, is_challenge=True)
  │     └─ Same parallel pattern
  │     └─ Context includes round1_compressed (not raw proposals)
  │     └─ snapshot_keys=ROUND2_KEYS
  │
  ├─ [SYNTHESIZING]
  │   _synthesize()
  │     └─ Planner receives all proposals + challenges + compressed Round 1
  │     └─ Returns comprehensive markdown document
  │
  ├─ [ARTIFACT GATE]
  │   All <write_file> artifacts in context["artifacts"]
  │   └─ Already reviewed per-agent during rounds
  │
  └─ [DONE]
      _write_session_log() → logs/session-{id}.json
      session_store.invalidate(project_path)
      return result dict
```

### 2.3 PipelineError Threshold

If more than 50% of agents in a round fail (after exhausting their 3-attempt retry budget), `PipelineError` is raised and the pipeline aborts. Individual agent failures below this threshold are logged and excluded from synthesis, but the pipeline continues.

### 2.4 Agent Retry Loop

```python
for attempt in range(1, MAX_RETRIES + 1):  # MAX_RETRIES = 3
    response = agent.respond(request + feedback_from_previous_failure)
    validation = validate_response(agent_name, task, response)
    if not validation["valid"]:
        feedback = validation["suggestions"]
        continue  # next attempt
    if "<write_file" in response:
        passed, review_feedback = _review_artifact(response, request)
        if not passed:
            feedback = review_feedback
            continue
    return success
raise ValidationError / ReviewError  # all attempts exhausted
```

---

## 3. Memory & Context Optimizations

### 3.1 Phase 1 — Snapshot Key Filtering

Each debate round receives only the context keys it actually needs:

```python
_SNAPSHOT_KEYS_ROUND1    = ["project_description"]
_SNAPSHOT_KEYS_ROUND2    = ["round1_compressed", "project_description", "errors"]
_SNAPSHOT_KEYS_SYNTHESIS = ["proposals", "challenges", "round1_compressed", "errors"]
```

Agents never receive the full context store dump. **Estimated savings: ~10–15% per agent call.**

### 3.2 Phase 2 — Compression Gate

After Round 1, raw proposals (potentially 1000–3000 tokens each) are compressed before being passed to Round 2 agents.

**Fallback chain (in order):**

1. **Self-authored summary:** Agents that include a `## Summary` block in their response — this text is extracted verbatim. Conflict-preserving by design (agents summarize their own position).
2. **LLM re-summarization:** Planner is called with all raw proposals and asked to produce bullet-point summaries.
3. **Character truncation:** Hard truncation to a token budget as last resort.

Result stored as `context["round1_compressed"]`. Raw Round 1 proposals are retained in `context["proposals"]` for synthesis but not forwarded to Round 2 agents. **Estimated savings: ~60–70% on Round 2 inputs.**

### 3.3 Phase 3 — Spec Content Deduplication

`spec.md` is read exactly once at `Orchestrator.__init__` and stored in `self.spec_content`. No file I/O on agent calls. `FileNotFoundError` is raised at construction time so failures are visible immediately rather than mid-session.

### 3.4 Token Budget Summary

| Mechanism | Estimated Savings |
|-----------|------------------|
| Snapshot key filtering (Phase 1) | ~10–15% per agent call |
| Compression gate (Phase 2) | ~60–70% on Round 2 inputs |
| `--resume` context continuity (Phase 6) | ~20–40% on repeated same-agent calls |
| Prompt caching via SDK (Phase 4) | **Eliminated** — not available via CLI |

> **Note:** Phase 4 (SDK + `cache_control: ephemeral`) was implemented and reverted. The net token position vs Phase 4 requires empirical measurement via Phase 7.5 benchmark gate.

---

## 4. Phase 6 CLI Session Persistence

### 4.1 Design Goals

Enable server-side context continuity across debate rounds without maintaining a persistent process. Each agent accumulates its own conversation history across rounds using the CLI `--resume` flag.

### 4.2 Session Key Model

```
key = f"{backend}:{agent_name}:{abs(project_path)}"
```

Examples:
- `claude:Architect:/home/ben/project/todo-cli` — Round 1 + Round 2 Architect share this
- `claude:Skeptic:/home/ben/project/todo-cli` — Skeptic never shares with Architect

### 4.3 Claude Session Resume Logic

```
First call for (backend, agent, project):
  → Generate UUID: session_id = str(uuid.uuid4())
  → Command: claude --print --session-id <uuid> --output-format json ...
  → On success: persist session_id to SessionStore

Subsequent call:
  → Retrieve session_id from SessionStore
  → Command: claude --print --resume <uuid> --output-format json ...
  → On --resume failure (non-zero returncode):
      → Retry once without --resume flag (stateless fallback)
      → Log warning: session_id = None
      → Do NOT raise — pipeline continues
```

### 4.4 Gemini Session Handling

Gemini CLI's `--resume latest` is **unsafe under `ThreadPoolExecutor`**. Concurrent threads racing to resume "latest" can cross-contaminate sessions. **Gemini runs stateless by default.** No session IDs are stored or retrieved for Gemini agents. Index-pinning via `--list-sessions` is deferred.

### 4.5 CLAUDECODE Environment Stripping

The MAS orchestrator runs inside a Claude Code session. The `CLAUDECODE` environment variable causes the Claude CLI to refuse to launch nested sessions.

**Every subprocess call strips this variable:**

```python
def _get_env(self) -> dict:
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    return env
```

This is enforced in `CLISession._get_env()`. It is **non-negotiable** and applies to every `subprocess.run()` call in the system, including retry calls.

### 4.6 CLICallResult Observability

Every CLI invocation returns:

```python
@dataclass
class CLICallResult:
    content: str
    session_id: Optional[str]    # None → stateless fallback
    returncode: int
    is_resumed: bool             # True → --resume was used
    duration_s: float
    input_tokens: Optional[int]  # input + cache_read + cache_creation
    output_tokens: Optional[int]
```

Both `session_id` and `is_resumed` are logged in `logs/session-{id}.json`. Operators verify `--resume` is being used by inspecting `is_resumed` in session logs.

### 4.7 Token Accounting — Cache Field Summing

Claude JSON output includes multiple token fields for cached inputs:

```python
input_tokens = (
    raw["input_tokens"]
    + raw.get("cache_read_input_tokens", 0)
    + raw.get("cache_creation_input_tokens", 0)
)
```

All three fields are summed to produce the canonical `input_tokens` value in `CLICallResult`. This ensures token accounting is complete even when prompt caching is active on the server side.

### 4.8 Failure Mode Contract

| Failure | Response |
|---------|----------|
| Binary not found at init | `BinaryNotFoundError` — fail fast |
| Session ID extraction failure | `session_id=None` → stateless fallback, log warning |
| `--resume` returns non-zero | Retry once without `--resume`; clear session_id |
| Gemini race condition | Stateless by design; no retry needed |
| LLM non-zero exit (no resume) | `BackendCallError` raised to caller |

---

## 5. Phase 7 & 8 Hardening

### 5.1 Exception Hierarchy (`exceptions.py`)

All MAS exceptions form a strict taxonomy inheriting from both `MASError` and `RuntimeError` for backward compatibility:

```
MASError(RuntimeError)
  ├─ BinaryNotFoundError      — CLI binary missing at init
  ├─ SessionError             — Subprocess call failure
  │    └─ SessionResumeError  — --resume retry exhausted
  ├─ BackendCallError         — LLM backend non-zero exit
  ├─ ValidationError          — Agent response validation exhausted (3 retries)
  ├─ ReviewError              — CodeReviewer returns FAIL after retries
  ├─ PipelineError            — >50% agents fail in a debate round
  └─ CompressionError         — Compression gate produces no summaries
```

**Design invariant:** All exceptions can be caught as `RuntimeError` for legacy compatibility while also being catchable as `MASError` for MAS-specific handling.

### 5.2 Session Log Integrity

Every session log (`logs/session-{id}.json`) is structured as:

```json
{
  "session_id": "uuid",
  "start_time": "ISO-8601",
  "end_time": "ISO-8601",
  "entries": [
    {
      "agent": "Architect",
      "backend": "claude",
      "model": "claude-sonnet-4-6",
      "round": 1,
      "status": "success",
      "duration_s": 12.4,
      "input_tokens": 1820,
      "output_tokens": 743,
      "retry_count": 0,
      "is_resumed": true,
      "skills_injected": true
    }
  ]
}
```

At `Orchestrator.__init__`, the previous session log is checked for a missing `end_time`. If absent, a warning is logged — this indicates the previous session was interrupted (process kill, crash). This is observability only; it does not block the new session.

### 5.3 Environment Stripping Audit

Phase 7.1 added `tests/test_env_stripping.py` with two test classes:

1. **`TestGetEnv`** — Unit tests confirming `CLISession._get_env()` strips `CLAUDECODE` in all forms and returns a copy (not `os.environ`)
2. **`TestSubprocessEnvStripping`** — Integration tests confirming `CLAUDECODE` is absent from the `env=` argument passed to `subprocess.run()` even when present in `os.environ`, including retry calls

### 5.4 Gemini Safety

Two invariants enforced in `CLISession`:
1. If backend is `"gemini"`, `session_id` must be `None` before the call (assertion)
2. No `--resume` or `--session-id` args are ever added to Gemini command lines

This prevents the race condition where concurrent `ThreadPoolExecutor` threads contest `--resume latest`.

### 5.5 Skills Token CI Enforcement (`scripts/lint_skills.py`)

Each `SKILL.md` must be ≤200 tokens (cl100k_base encoding via `tiktoken`). The linter:
- Iterates all `skills/*/SKILL.md` files
- Encodes with `tiktoken.get_encoding("cl100k_base")`
- Exits non-zero if any file exceeds 200 tokens
- Runs as a pre-commit hook; blocks commits that violate the cap

### 5.6 Skill Injection Observability

When a skill is injected into an agent's system prompt:
- `session_log` entry: `"skills_injected": true`
- Full assembled prompt written to `logs/prompts/{timestamp}_{agent}.txt`

When no skill file exists for an agent, the base prompt is used unchanged and `"skills_injected": false` is logged.

### 5.7 Regression Test Suite (`tests/regression_suite.py`)

Phase 8 added a comprehensive regression suite covering:

| Test Class | What It Validates |
|------------|------------------|
| `TestExceptionHierarchy` | All subclasses inherit `MASError` + `RuntimeError`; `SessionResumeError` is a `SessionError` |
| `TestContextStore` | Scalar r/w, list append, snapshot isolation, key filtering, 10-thread concurrent append (500 items) |
| `TestCLISessionParsing` | JSON result extraction, plain token counting, cache field summing, non-JSON fallback, non-zero returncode |
| `TestAgentBackendCallError` | `BackendCallError` raised on non-zero; success returns content; MASError hierarchy intact |
| `TestOrchestratorBinaryCheck` | `BinaryNotFoundError` for missing binaries; no error for present commands |

---

## 6. Developer Guide

### 6.1 Adding a New Agent

1. **Define the factory** in `agents.py`:

```python
def make_my_agent(cfg: dict, project_path: Optional[str]) -> Agent:
    return Agent(
        name="MyAgent",
        role="my_agent",
        system_prompt="""You are a specialist in X...""",
        project_path=project_path,
        backend=cfg.get("backend", "claude"),
        model=cfg.get("model", "claude-sonnet-4-6"),
        temperature=cfg.get("temperature", 0.7),
        session_store=None,  # injected by build_agents()
    )
```

2. **Register it** in `AGENT_FACTORIES`:

```python
AGENT_FACTORIES = {
    ...
    "my_agent": make_my_agent,
}
```

3. **Create the skill file** `skills/MyAgent/SKILL.md` (optional but recommended):

```markdown
## Your Specialized Skills

- Constraint 1
- Constraint 2
```

Run `python scripts/lint_skills.py` to verify token count ≤200.

4. **Add to config** if non-default temperature needed:

```yaml
agents:
  my_agent:
    temperature: 0.75
```

### 6.2 Adding a New Skill

Skills are plain Markdown files. Rules:

- **≤200 tokens** (enforced by CI linter)
- **Markdown only** — no YAML frontmatter, no special tags
- **Additive Rule:** Skills append to the base prompt; they must not duplicate or override role identity instructions already in the system prompt
- A `skills/_shared/` directory is created **only** when identical content appears verbatim in ≥2 agent files — no preemptive shared abstractions

**Prompt structure after injection:**
```
1. Role identity        (AGENT_PROMPTS[agent_name])
2. Specialized Skills   (skills/{AgentName}/SKILL.md)
3. Dynamic context      (ContextStore snapshot, filtered by round)
4. Task                 (user request)
```

### 6.3 Running the Test Suite

```bash
# Full regression suite
python -m pytest tests/regression_suite.py -v

# Environment stripping audit
python -m pytest tests/test_env_stripping.py -v

# Skill token linter
python scripts/lint_skills.py

# Full run (all tests + linter)
python -m pytest tests/ -v && python scripts/lint_skills.py
```

### 6.4 Running the MAS

```bash
# Full debate
python main.py "Build a real-time analytics dashboard" --project-path /path/to/project

# Continue (write spec.md + tasks.md) after human review
python main.py "..." --mode continue --project-path /path --output report.md

# Single agent / single task
python main.py "..." --mode agent --agent architect --task write_tasks_md --project-path /path

# Quiet (suppress per-agent output)
python main.py "..." --quiet

# Headless + JSON output (for scripting)
python main.py "..." --headless --format json
```

### 6.5 Interpreting Session Logs

```bash
# Check if --resume is being used
cat logs/session-{id}.json | python -m json.tool | grep is_resumed

# Token usage per agent
cat logs/session-{id}.json | python -m json.tool | grep -A2 '"agent"'

# CLI call detail (newline-delimited JSON)
cat logs/cli_calls.log | python -c "import sys,json; [print(json.dumps(json.loads(l), indent=2)) for l in sys.stdin]"

# Full prompts (when skills injected)
ls logs/prompts/
cat logs/prompts/{timestamp}_{agent}.txt
```

### 6.6 The Additive Rule

> **Never replace. Always append.**

This applies to all extension points in the system:

| Extension Point | Rule |
|----------------|------|
| SKILL.md content | Appended after base system prompt, never replaces it |
| Context keys | New keys added to `ContextStore`; existing keys not renamed |
| Exception types | New subclasses of existing hierarchy; no base class changes |
| Agent factories | Added to `AGENT_FACTORIES` dict; no existing factory modified |
| Snapshot key sets | New `_SNAPSHOT_KEYS_*` constants; existing ones not mutated |

Violating the Additive Rule breaks session continuity, existing tests, and log schemas simultaneously.

### 6.7 Config Reference (`config.yaml`)

```yaml
defaults:
  backend: claude              # "claude" | "gemini"
  model: claude-sonnet-4-6
  temperature: 0.7

agents:
  planner:
    temperature: 0.5           # deterministic for JSON selection output
  code_reviewer:
    temperature: 0.3           # deterministic for PASS/WARN/FAIL
  skeptic:
    temperature: 0.9           # creative challenges

backends:
  claude:
    command: /path/to/claude   # validated at Orchestrator.__init__
    args: ["--print", "--permission-mode", "bypassPermissions"]
  gemini:
    command: gemini
    args: ["-m", "{model}", "--yolo"]

debate:
  max_rounds: 2
  min_agents: 3
  max_agents: 5

cli_timeout_s: 120             # per subprocess.run() call
```

---

## Appendix: Phase Completion Status

| Phase | Feature | Status |
|-------|---------|--------|
| 1 | Snapshot key filtering | ✓ |
| 2 | Compression gate | ✓ |
| 3 | Spec content deduplication | ✓ |
| 4 | SDK + prompt caching | Superseded by Phase 6 |
| 5 | Skills system | ✓ |
| 6 | CLI session persistence | ✓ |
| 7.1 | CLAUDECODE env audit + tests | ✓ |
| 7.2 | Session invalidation after synthesis | ✓ |
| 7.3 | Gemini stateless safety | ✓ |
| 7.4 | `--resume` retry contract | ✓ |
| 7.5 | Benchmark gate (token ROI) | ✓ |
| 7.6 | `CLICallResult` observability fields | ✓ |
| 7.7 | Skills token CI enforcement | ✓ |
| 8.1 | Structured exception hierarchy | ✓ |
| 8.2 | Session log integrity check | ✓ |
| 8.3 | Skill injection observability | ✓ |
| 8.4 | Regression test suite | ✓ |
