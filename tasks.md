# MAS Implementation Tasks

## Completed

- [x] Phase 1: Snapshot Key Filtering — `ContextStore.snapshot(keys=[...])` filtering
- [x] Phase 2: Compression Gate — `_compress_proposals()` with `## Summary` extraction
- [x] Phase 3: Spec Content Deduplication — `self.spec_content` cached at init
- [x] Phase 4: SDK Migration + Prompt Caching — *superseded by Phase 6*
- [x] Phase 5: Skills System — per-agent `SKILL.md` injection with token cap enforcement
- [x] Phase 6: CLI Session Persistence — implemented with `SessionStore` and `CLISession`

---

## Phase 7 — Session Correctness & Observability

Phase 7 fixes four concrete bugs identified in the Phase 6 audit, closes a spec compliance gap,
and adds durability hardening. All tasks are in `backends/session_store.py` and
`backends/cli_session.py` unless noted.

### Task 7.1 — Lock `SessionStore.get()` + Use `realpath()` [CRITICAL]

**File:** `backends/session_store.py`

**Problems:**
1. `get()` reads `self._sessions` without holding `self._lock`. Under `ThreadPoolExecutor`, a
   concurrent `set()` or `invalidate()` can mutate the dict mid-read.
2. `_get_key()` uses `os.path.abspath()` — symlinked project directories produce two distinct
   keys for the same on-disk project, silently breaking session identity.

**Fix:**

```python
def _get_key(self, backend: str, agent_name: str, project_path: str) -> str:
    # realpath resolves symlinks; abspath does not
    abs_path = os.path.realpath(project_path)
    return f"{backend}:{agent_name}:{abs_path}"

def get(self, backend: str, agent_name: str, project_path: str) -> Optional[str]:
    key = self._get_key(backend, agent_name, project_path)
    with self._lock:
        return self._sessions.get(key)
```

**Acceptance:**
- Unit test: concurrent `set` + `get` on same key from 20 threads; no `RuntimeError` or stale
  reads after 1000 iterations.
- Unit test: symlinked path and real path produce the same session key.

---

### Task 7.2 — Pre-register UUID Before Subprocess [CRITICAL]

**File:** `backends/cli_session.py`

**Problem:** Two threads for the same `(backend, agent_name, project_path)` both call `get()`
→ `None`, both generate separate UUIDs, both launch `--session-id` first calls. Last `set()`
wins; first UUID is orphaned (live server-side session, never resumed).

**Fix:** Call `session_store.set(uuid)` immediately after generating the UUID — before the
subprocess. If a second thread calls `get()` for the same key before the first thread returns,
it will receive the in-progress UUID and proceed with `--resume`.

```python
# In CLISession.call(), first-call branch:
session_id = str(uuid.uuid4())
self.session_store.set(self.backend, self.agent_name, self.project_path, session_id)
cmd.extend(["--session-id", session_id])
```

**Acceptance:** Test: two threads simultaneously call `CLISession.call()` on same agent key
with a mock subprocess that sleeps 0.1s. After both return, exactly one UUID exists in the
store and both calls returned a result.

---

### Task 7.3 — Per-Agent `invalidate_agent()` [HIGH]

**File:** `backends/session_store.py`, `backends/cli_session.py`

**Problem:** On `--resume` failure, `invalidate(project_path)` destroys sessions for all agents
in the project. Architect failure nukes Skeptic's session.

**Fix:** Add a scoped method and use it in the retry path.

```python
# session_store.py
def invalidate_agent(self, backend: str, agent_name: str, project_path: str):
    """Clear only this agent's session for the given project."""
    key = self._get_key(backend, agent_name, project_path)
    with self._lock:
        self._sessions.pop(key, None)
        self._save()
```

```python
# cli_session.py — retry branch:
self.session_store.invalidate_agent(self.backend, self.agent_name, self.project_path)
```

Note: `invalidate(project_path)` (all-agents) remains valid **only** after synthesis completes,
as per §5.1. It must never be used in error paths.

**Acceptance:** Test: Skeptic and Architect sessions both stored; Architect's `--resume` fails;
only Architect's key is removed from store; Skeptic's key persists.

---

### Task 7.4 — Retry Depth Guard [HIGH]

**File:** `backends/cli_session.py`

**Problem:** `self.call(prompt, extra_args)` is called recursively without a depth limit. A
persistent failure (service down, auth error) causes infinite recursion → stack overflow.

**Fix:** Add `_retry_depth: int = 0` parameter; raise `RuntimeError` after depth > 1.

```python
def call(
    self,
    prompt: str,
    extra_args: Optional[List[str]] = None,
    _retry_depth: int = 0,
) -> CLICallResult:
    ...
    if res.returncode != 0:
        if is_resumed and _retry_depth == 0:
            self.session_store.invalidate_agent(...)
            return self.call(prompt, extra_args, _retry_depth=1)
        return CLICallResult(
            content=res.stderr.strip() or res.stdout.strip(),
            returncode=res.returncode,
            duration_s=duration,
        )
```

**Acceptance:** Test: subprocess always returns non-zero; verify `call()` returns after exactly
2 attempts (initial + 1 retry) without raising `RecursionError`.

---

### Task 7.5 — Atomic `_save()` via Temp File [MEDIUM]

**File:** `backends/session_store.py`

**Problem:** `_save()` writes directly to `sessions.json`. A process crash or SIGKILL during
write produces a truncated/corrupt file. `_load()` silently discards all sessions on
`json.JSONDecodeError`.

**Fix:** Write to `sessions.json.tmp`, then `os.replace()` (atomic on POSIX; best-effort on
Windows).

```python
def _save(self):
    os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
    tmp_path = self.storage_path + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(self._sessions, f, indent=2)
    os.replace(tmp_path, self.storage_path)
```

Note: `_save()` is always called while the caller holds `self._lock`, so the tmp file is not
raced by other threads.

**Acceptance:** Test: kill process mid-write (simulate via mock); `_load()` on next init
produces valid empty dict, not corrupt state.

---

### Task 7.6 — Write `is_resumed`/`duration_s` to Session Log [MEDIUM]

**Spec reference:** §5.7

**Problem:** `CLICallResult.is_resumed` and `duration_s` are populated but never written to
`logs/session-{id}.json`. Operators cannot verify `--resume` is being used.

**File:** Wherever the Orchestrator writes per-agent-call entries to session JSON (likely
`agents.py` or `orchestrator.py`).

**Fix:** Include `CLICallResult` fields in the per-call log entry. Also add `resume_degraded`
flag to surface silent fallback events — operators must know when continuity was lost.

```python
log_entry = {
    "agent": agent_name,
    "timestamp": datetime.utcnow().isoformat(),
    "session_id": result.session_id,
    "is_resumed": result.is_resumed,
    "resume_degraded": result.is_resumed is False and session_existed_before_call,
    "duration_s": result.duration_s,
    "input_tokens": result.input_tokens,   # from CLI JSON response
    "output_tokens": result.output_tokens, # from CLI JSON response
    "skills_injected": bool(skill_content.strip()),
}
```

Note: `resume_degraded: true` is the correct response to resume failure — **not** a hard abort.
Synthesis output should note degraded agents, but the session should complete.

**CLICallResult additions required:**

```python
@dataclass
class CLICallResult:
    content: str
    session_id: Optional[str] = None
    returncode: int = 0
    is_resumed: bool = False
    duration_s: float = 0.0
    input_tokens: Optional[int] = None   # add
    output_tokens: Optional[int] = None  # add
```

**Acceptance:** Run one debate session; open `logs/session-*.json`; verify every agent call
entry contains `is_resumed` (bool), `duration_s` (float > 0), and `resume_degraded` (bool).

---

### Task 7.7 — Session TTL and Stale-Session Expiry [LOW]

**File:** `backends/session_store.py`

**Problem:** Session UUIDs are stored indefinitely. If the Claude CLI server expires a session
(e.g., after 24h inactivity), `--resume <uuid>` returns non-zero, triggering the retry path on
every first call of a new run. The store accumulates dead sessions.

**Fix:** Store `(session_id, created_at_iso)` per key. On `get()`, return `None` if age exceeds
`ttl_hours` (default: 23h, configurable). Expired entries are lazily pruned on `get()`.

```python
# Storage format change:
# { "claude:Architect:/abs/path": {"id": "uuid", "created_at": "2026-03-18T10:00:00"} }
```

**Migration:** `_load()` must handle both old string format and new dict format gracefully
(string → treat as no `created_at` → expire immediately on next `get()`).

**Acceptance:** Test: set a session with `created_at` 24h ago; `get()` returns `None`; entry
is removed from `_sessions`.

---

### Task 7.8 — Write-Coalescing to Reduce Lock Contention [LOW]

**File:** `backends/session_store.py`

**Problem:** Every `set()` acquires the lock and does a full JSON file rewrite. With 5 parallel
agents, this serializes disk I/O under the lock. On cloud VMs or NFS mounts, this can stall
all agent threads.

**Fix:** Debounce disk writes — flush at most once per 100ms from a background writer thread.
In-memory state is always current; only persistence is delayed.

```python
def _schedule_save(self):
    """Debounced save — flushes to disk at most every 100ms."""
    # Cancel pending flush, reschedule
    if self._save_timer:
        self._save_timer.cancel()
    self._save_timer = threading.Timer(0.1, self._flush)
    self._save_timer.daemon = True
    self._save_timer.start()
```

`set()` and `invalidate_agent()` call `_schedule_save()` instead of `_save()` directly.
`clear_all()` and post-synthesis `invalidate()` call `_flush()` synchronously (must persist).

**Crash window:** ≤100ms of session ID loss — acceptable given Task 7.4's retry path.

**Acceptance:** Benchmark: 5 threads calling `set()` concurrently; total wall time ≤ 200ms
(vs current ~500ms with sequential lock+write).

---

### Task 7.9 — Path Traversal: Use `realpath` on Both Sides of Guard [MEDIUM]

**File:** `agents.py` (write_file tag parser)

**Problem:** Security identified that `os.path.join(abs_project_path, file_path)` discards the
prefix when `file_path` is absolute. The `startswith(abs_project_path)` guard then fails for
sibling-directory paths (e.g., `/home/ben/project-evil/payload`).

**Fix:** Normalize both sides with `realpath` and use trailing-separator comparison.

```python
abs_base = os.path.realpath(abs_project_path)
full_path = os.path.realpath(os.path.join(abs_base, file_path))
if not full_path.startswith(abs_base + os.sep):
    raise ValueError(f"Path traversal rejected: {file_path}")
```

**Acceptance:** Test: `../sibling/evil`, `/etc/passwd`, and `/home/user/project-evil/x` all
raise `ValueError`. A legitimate `subdir/file.py` passes.

---

### Task 7.10 — File Permissions for Session Store and Logs [LOW]

**File:** `backends/session_store.py`, `Orchestrator.__init__`

**Problem:** `.mas/sessions.json` contains live Claude session UUIDs — any user with read
access to the project directory can hijack active sessions. `logs/` contains full prompt text
including potentially sensitive project data.

**Fix:**

```python
# session_store.py _save():
os.makedirs(os.path.dirname(self.storage_path), exist_ok=True, mode=0o700)
# write the file, then:
os.chmod(self.storage_path, 0o600)

# orchestrator.py, logs dir creation:
os.makedirs("logs", exist_ok=True, mode=0o700)
```

**Acceptance:** After one session, verify `stat .mas/sessions.json` shows `-rw-------` and
`stat logs/` shows `drwx------`.

---

## Phase 6.5 — Gemini Session Pinning (Conditional)

**Prerequisite:** Phase 6.7 measurement must show Gemini's stateless re-send cost is
significant. Do not implement speculatively.

**Constraint:** Either commit to Claude-only for Phase 6 (document the constraint explicitly),
or block Phase 6.5 until Gemini parity is confirmed viable. "Deferred" is not the same as
"decided." Shipping without documenting the backend constraint is incomplete.

---

## Phase 6.6 — Parallelism Recovery (Conditional)

**Prerequisite:** Benchmark Phase 6 baseline (with `--resume`) vs Phase 4 (SDK); confirm
serialization regression exists after Task 7.8 ships. Task 7.8 may render this unnecessary.

If per-agent session locks still cause measurable overhead after debouncing, implement
`SessionPool` with N=3 pre-warmed sessions per `(backend, agent_name)`.

---

## Phase 6.7 — Token Budget Measurement

After Task 7.6 ships (token counts in session log): measure actual `--resume` savings vs lost
prompt caching from Phase 4 SDK.

**Methodology:**
1. Run 5 debate sessions with `--resume` active (Phase 6 baseline)
2. Run 5 debate sessions with `--resume` disabled (stateless baseline)
3. Compare `input_tokens` per agent per round
4. If Phase 6 net cost > Phase 4 net cost, re-evaluate SDK path as `runner: "sdk" | "cli"` flag

**Gate:** This measurement must complete before declaring Phase 6 a net token win over Phase 4.

---

## Invariants (Do Not Regress)

- Phase 1 snapshot filtering: `ContextStore.snapshot(keys=[...])` must remain in all call sites
- Phase 2 compression gate: `_compress_proposals()` must run after Round 1; CLI session does
  not eliminate this (safety valve for long sessions)
- Phase 3 spec deduplication: `self.spec_content` cached at init; no per-call file reads
- Phase 5 skills injection: `_build_system_prompt()` wraps every agent call; CLI backend is
  transparent to this layer
- CLAUDECODE stripping: `env.pop("CLAUDECODE", None)` in every subprocess call — never skip
- Task 7.3 invariant: `invalidate_agent()` must be used in retry paths; `invalidate()` (all-
  agents) is only valid after synthesis, never in error paths
- Task 7.6 invariant: resume failure must emit `resume_degraded: true` in session log and
  surface in synthesis output — never silently absorbed