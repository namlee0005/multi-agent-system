# MAS Implementation Tasks

## Completed

- [x] Phase 1: Snapshot Key Filtering — `ContextStore.snapshot(keys=[...])` filtering
- [x] Phase 2: Compression Gate — `_compress_proposals()` with `## Summary` extraction
- [x] Phase 3: Spec Content Deduplication — `self.spec_content` cached at init
- [x] Phase 4: SDK Migration + Prompt Caching — *superseded by Phase 6*
- [x] Phase 5: Skills System — per-agent `SKILL.md` injection with token cap enforcement

---

## Active

### Phase 6: CLI Session Persistence

Implement "one CLI session per agent role per project" using `--resume <session-id>` per subprocess call. Reverts Phase 4 SDK dependency. Provides server-side context continuity across debate rounds with per-agent session isolation.

**Session key:** `(backend, agent_name, project_path)` — one session per agent role, not per project. This gives Round 2 agents continuity with their Round 1 context while preventing cross-agent bleed.

**Implementation order:** 6.0 → 6.1 → 6.2 → 6.3 → 6.4 (do not reorder; each blocks the next).

---

#### 6.0 — CLAUDECODE Environment Fix (Priority: Critical — ships first)

- [ ] In `agents.py` (or `CLISession.call()`): strip `CLAUDECODE` from subprocess env
  ```python
  env = os.environ.copy()
  env.pop("CLAUDECODE", None)
  subprocess.run([...], env=env, ...)
  ```
- [ ] Acceptance criterion: `claude --print ...` succeeds when invoked from inside a Claude Code session
- [ ] Verify unsetting `CLAUDECODE` does not break other Claude Code hooks in the environment

---

#### 6.1 — SessionStore (Priority: High)

- [ ] Create `backends/session_store.py`
  - `CLISessionConfig(BaseModel)`: `backend: str`, `command: str`, `agent_name: str`, `project_path: str`, `model: str`
  - `CLICallResult(BaseModel)`: `content: str`, `session_id: str | None`, `returncode: int`, `is_resumed: bool`, `duration_s: float`
  - `SessionStore`: loads/persists `.mas/sessions.json`
    - Key: `(backend, agent_name, project_path)` — per-agent isolation
    - Maps key → `session_id: str | None`
    - `get(backend, agent_name, project_path) -> str | None`
    - `set(backend, agent_name, project_path, session_id: str) -> None`
    - `invalidate(project_path: str) -> None` — clears all sessions for a project post-synthesis
    - File lock on `.mas/sessions.json` writes (`threading.Lock`)
- [ ] Create `.mas/` directory; add `.mas/sessions.json` to `.gitignore`

---

#### 6.2 — CLI Binary Validation (Priority: High)

- [ ] In `Orchestrator.__init__()`: validate CLI binary availability
  ```python
  import shutil
  for backend, cfg in self.config["backends"].items():
      cmd = cfg["command"]
      if not shutil.which(cmd) and not os.path.isfile(cmd):
          raise RuntimeError(f"Backend binary not found: {cmd!r}")
  ```
- [ ] Fail fast at init — not on first agent call 30 seconds into a session

---

#### 6.3 — CLISession Call Integration (Priority: High)

- [ ] Create `backends/cli_session.py` — `CLISession` class
  - `CLISession(backend, agent_name, project_path, command, model, session_store)`
  - `call(prompt: str, extra_args: list[str] = []) -> CLICallResult`
    - Claude path:
      - Pre-generate UUID at `Orchestrator.__init__` via `uuid.uuid4()`; store in `SessionStore`
      - First call: `[command, --print, --output-format, json, --session-id, <uuid>, --model, <model>]`
      - Subsequent calls: `[command, --print, --output-format, json, --resume, <uuid>, --model, <model>]`
      - Parse `session_id` from JSON stdout on first call; confirm matches pre-generated UUID
    - Gemini path:
      - **Stateless by default** — no `--resume` flag
      - Rationale: `--resume latest` is unsafe under `ThreadPoolExecutor` (race condition)
    - All paths: `env.pop("CLAUDECODE", None)` before spawn (from Task 6.0)
    - On `returncode != 0` with `--resume`: retry once without `--resume`; call `session_store.invalidate()` for that agent key
    - On session ID extraction failure: `session_id=None`, log warning, continue stateless — do not raise

- [ ] Update `agents.py`: replace `call_llm()` subprocess invocations with `CLISession.call()`
  - Wire `CLICallResult.is_resumed` and `session_id` into session JSON log entry
  - All Claude calls use pre-generated UUID session IDs (no stdout extraction needed)

- [ ] Update `orchestrator.py`
  - Init `SessionStore` at `__init__`
  - Call `session_store.invalidate(project_path)` after synthesis completes
  - Remove Anthropic SDK import and `cache_control` logic (Phase 4 revert)
  - Pass `SessionStore` instance to `run_agent()` call sites

---

#### 6.4 — Phase 4 Revert + Config + Docs (Priority: Medium)

- [ ] Remove `anthropic` SDK dependency from `requirements.txt` / `pyproject.toml`
- [ ] Remove SDK-specific code paths from `orchestrator.py`
- [ ] Update `config.yaml`: add `cli_timeout_s: 120`
- [ ] Update `spec.md`: §5 replaced with Phase 6 spec; §7 CLI Migration Rationale added *(done by Planner)*
- [ ] Update `tasks.md`: mark Phase 4 superseded *(done by Planner)*

---

#### 6.4.1 — Validate Claude stdout JSON Format (Priority: High, blocks 6.3)

- [ ] Run: `claude --print --output-format json --session-id <test-uuid> "hello"` outside Claude Code
- [ ] Confirm: `session_id` field present in JSON response
- [ ] Confirm: pre-generated UUID matches returned `session_id`
- [ ] Document exact JSON schema in `backends/cli_session.py` docstring
- [ ] If `session_id` absent: fall back to UUID-only strategy (pre-generate, never extract); update 6.3 accordingly

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