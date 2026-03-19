# Multi-Agent Project Advisor Report

**Project:** Design and implement a real-time notification mechanism for the Multi-Agent System. The system must immediately notify the Orchestrator/User when an agent completes a task, avoiding the current manual polling/waiting delay. Consider file-based signals, webhooks, or inter-process communication.

## Selected Specialist Agents
1. **Researcher**
2. **Architect**
3. **Backend_Dev**
4. **Security**

## Debate Round 1: Initial Proposals
### Researcher
### Real-Time Notification Mechanism for Multi-Agent System

**Analysis of Options:**

1.  **File-based Signals:**
    *   **Evaluation:** This method involves agents signaling completion by creating, modifying, or deleting specific files, which the Orchestrator then polls. While conceptually simple, it is highly unsuitable for real-time notification in a multi-agent system. File system polling introduces significant latency, is resource-intensive (disk I/O, CPU for polling), and is inherently prone to race conditions and inconsistent state without complex locking mechanisms. Operating system-level file event notifications (e.g., Linux `inotify`) offer lower latency but are non-portable and require careful management to avoid event floods, making them less reliable for general purpose eventing.
    *   **Evidence:** Modern, high-performance, or distributed systems consistently avoid file-based signaling for inter-process or inter-service communication due to its inherent limitations in latency, reliability, and scalability. Its use is generally confined to configuration reloads or highly specialized, low-frequency eventing in monolithic applications.

2.  **Inter-Process Communication (IPC):**
    *   **Evaluation:** IPC encompasses various mechanisms (e.g., Unix domain sockets, named pipes, shared memory, message queues like Redis Pub/Sub) that facilitate communication between processes *on the same host*. IPC offers the lowest latency and highest throughput for co-located agents due to avoiding network overhead. It's highly efficient for tightly coupled components that demand speed.
    *   **Evidence:** Unix domain sockets are widely adopted in high-performance local service communication (e.g., Nginx proxying to application servers) due to their efficiency. Message brokers like Redis, when used locally, can achieve millions of messages per second in pub/sub patterns, as demonstrated by various benchmarks. This pattern is robust and has a mature ecosystem.
    *   **Limitation:** The primary constraint is geographical locality; IPC solutions are typically bounded to a single machine. If agents are distributed across multiple hosts, native IPC mechanisms become unviable, necessitating a network-based alternative.

3.  **Webhooks:**
    *   **Evaluation:** Webhooks utilize standard HTTP POST requests to deliver event notifications to a pre-configured URL. This approach aligns perfectly with event-driven architectures and distributed systems. It offers strong decoupling between the notifying agent and the recipient (Orchestrator/User), enabling flexible deployment and asynchronous processing. Agents simply make an HTTP call upon task completion, which the Orchestrator listens for.
    *   **Evidence:** Webhooks are the industry standard for real-time event notification in virtually all major SaaS platforms and microservice architectures (e.g., GitHub, Stripe, Slack, Twilio). This demonstrates extreme maturity, robust error handling patterns (retries, exponential backoff, dead-letter queues), and vast community and tool support. Performance is excellent for typical notification loads, with modern HTTP/2 and efficient server implementations capable of handling thousands of requests per second.
    *   **Advantage:** Unparalleled flexibility for distributed deployments and ease of integration with diverse client applications (web UIs, other services).

**Recommendation:**

For the Multi-Agent System's real-time notification mechanism, **Webhooks** are the strongly recommended solution.

**Justification:**

1.  **Scalability and Distribution:** Webhooks inherently support agents distributed across various machines or containers, future-proofing the system as it scales or evolves towards more distributed architectures. This is a critical advantage for a "Multi-Agent System" design.
2.  **Decoupling and Modularity:** Webhooks foster loose coupling; agents only need to know the webhook endpoint to send notifications, enhancing modularity and simplifying maintenance.
3.  **Maturity and Ecosystem:** The webhook pattern is exceptionally mature, benefiting from extensive best practices, libraries, and tools for reliability (e.g., retry logic, idempotency), security (e.g., HMAC signatures, TLS), and observability. This significantly reduces development complexity and increases system robustness.
4.  **User-Friendly Integration:** Notifying an "Orchestrator/User" (which may involve a web dashboard, CLI, or another service) is naturally and efficiently handled by an HTTP-based mechanism, offering broad compatibility.

While IPC (specifically a Redis Pub/Sub pattern) could offer marginally lower latency for a strictly co-located system with extremely high-throughput demands, the overall benefits of webhooks—flexibility, scalability, and robust ecosystem—make them the superior and more future-proof choice for a multi-agent system. File-based signals are actively discouraged for real-time applications due to their inherent limitations.

### Architect
Now I have a thorough understanding of the system. Let me provide the architectural analysis and generate the `tasks.md`.

---

## Architect Analysis: Real-Time Notification Mechanism

### Problem Statement

The current system uses `ThreadPoolExecutor` + `as_completed()` which is already non-blocking _within_ a session. The real gap is **cross-process / cross-session notification**: when an agent subprocess completes (via `subprocess.run`), the parent receives nothing until the blocking call returns. There's no mechanism to stream progress, surface partial completions, or notify an external observer (UI, webhook consumer, parent process).

### Architecture Recommendation: Named Pipe + Event Bus (In-Process)

**Verdict: Avoid over-engineering.** This is a single-process Python app. No microservices, no Redis pub/sub, no webhooks needed. The right solution is layered:

```
  Agent Thread                  Orchestrator Main Thread
  ─────────────────             ────────────────────────
  subprocess.run(cmd)
        │
        │  completes
        ▼
  _emit_event(AgentDoneEvent)──► queue.SimpleQueue
                                        │
                                        ▼
                                 EventDispatcher.dispatch()
                                        │
                           ┌───────────┴────────────┐
                           ▼                        ▼
                  ConsoleNotifier          FileSignalNotifier
                  (live progress)          (logs/events.jsonl)
                                                    │
                                                    ▼
                                        External observer polls
                                        or tails the file
```

**Layer 1 — In-process event queue** (`queue.SimpleQueue`): Zero-latency, thread-safe, no external deps. Agents push `AgentDoneEvent` objects when `subprocess.run` returns. A dedicated dispatcher thread drains the queue.

**Layer 2 — File-based signal** (`logs/events.jsonl`): Append-only newline-delimited JSON. Any external process (`tail -f`, a UI, a CI step) can `inotify`/poll this file. Solves the "notify Orchestrator/User" use case without a server.

**Layer 3 — Optional webhook** (future): The dispatcher can POST to a configured URL if `notification.webhook_url` is set in config. Add only when needed.

### Why Not Alternatives

| Option | Verdict |
|--------|---------|
| Redis pub/sub | Requires external service. Overkill for a single-process tool |
| asyncio + SSE | Requires full async rewrite of the subprocess layer |
| OS signals (SIGUSR1) | Non-portable, hard to carry payload |
| Polling loop | Current problem — we're solving this |
| Named pipes (FIFO) | Good for IPC but `events.jsonl` is simpler and inspectable |

### Data Model

```python
@dataclass
class AgentEvent:
    event_type: Literal["agent_started", "agent_done", "agent_failed", "round_done"]
    session_id: str
    agent_key: str
    agent_name: str
    round: str
    timestamp: str  # ISO 8601
    duration_s: Optional[float] = None
    status: Optional[str] = None   # "success" | "error" | "validation_failed"
    detail: Optional[str] = None
```

### Risks

1. **Queue backpressure**: If dispatcher thread falls behind (slow file I/O, slow webhook), queue grows unboundedly. Mitigate with `maxsize` + dropped-event counter.
2. **File rotation**: `events.jsonl` grows forever. Add session-scoped filenames (`logs/events-{session_id}.jsonl`).
3. **Coupling**: Don't let agents import the event bus directly — keep emission in `_call_agent` to preserve separation.

---



The `tasks.md` has been written. Here's the architectural summary:

**Recommended approach: In-process event queue + file-based signal**

- `queue.SimpleQueue` — zero-latency, thread-safe, no external deps
- Background `EventDispatcher` thread drains events to registered listeners
- `FileSignalNotifier` writes `logs/events-{session_id}.jsonl` — any external observer can `tail -f` or poll it
- `ConsoleNotifier` gives live per-agent status in the terminal
- Optional `WebhookNotifier` (config-gated, stdlib only) for remote notification

**Key design decisions:**
1. `emit()` is non-blocking — agent threads are never delayed by notification I/O
2. No new dependencies — stdlib `queue`, `threading`, `urllib`
3. Emission points in `_call_agent()` (not inside `Agent.respond()`) to preserve agent/orchestrator separation
4. `event_bus.stop()` flushes before session end so no events are lost

8 tasks total, ordered by dependency. TASK-01 through TASK-05 are the critical path (P0/P1).

### Backenddev
## Real-Time Notification: Backend Proposal

### Current Problem

The system runs fully in-process via `ThreadPoolExecutor` + blocking `subprocess.run(timeout=600)`. There's zero cross-process notification — external observers (CLI, dashboards, humans) must re-invoke or tail log files to know when anything completes. The session log isn't even flushed to disk until the entire session ends (`orchestrator.py:125`).

---

### Recommendation: UNIX Named Pipes + SSE over FastAPI

**Do not reach for Redis or WebSockets.** This system is single-machine Python — the right tool is lightweight IPC, not a message broker.

#### Layer 1: Named Pipe (FIFO) for in-process → external signaling

Each agent completion writes a structured event to a named pipe at `/tmp/mas-events.fifo`. This is zero-dependency, low-latency, and works across processes on the same machine.

```python
# In orchestrator.py — after each future completes (line ~515)
import json, os, stat

FIFO_PATH = "/tmp/mas-events.fifo"

def _emit_event(event: dict):
    if os.path.exists(FIFO_PATH):
        with open(FIFO_PATH, "w") as f:
            f.write(json.dumps(event) + "\n")
```

Event schema:
```json
{"ts": "2026-03-13T12:36:37Z", "session_id": "ad1d77", "round": 1, "agent": "Architect", "status": "done", "duration_s": 4.2}
```

#### Layer 2: FastAPI SSE endpoint as the notification sink

A thin FastAPI sidecar reads the FIFO and fans events out to connected SSE clients (CLI, browser, orchestrator hooks). This keeps the orchestrator decoupled from consumers.



#### Layer 3: Flush session log incrementally, not at the end

The current `_log_lock` pattern is correct — just move the flush inside the existing lock block in `orchestrator.py:125` so each agent completion is persisted immediately:

```python
# orchestrator.py — append to session log after each round entry
with self._log_lock:
    self.session_log["rounds"].append(entry)
    # Flush incrementally
    with open(self._session_log_path, "w") as f:
        json.dump(self.session_log, f, indent=2)
```

---

### Why Not Redis Pub/Sub or WebSockets?

| Option | Why skip it |
|---|---|
| Redis pub/sub | Adds an external process dependency for a single-machine tool |
| WebSockets | Stateful, requires connection management — SSE is read-only and simpler |
| `inotify`/file watching | More complex, OS-specific, no structured event schema |
| Named pipe + SSE | Zero new dependencies, structured JSON events, works with `curl` |

---

### Integration Points

- `orchestrator.py:515` — emit after each `future.result()` in the round loop
- `orchestrator.py:125` — flush session log per-event, not once at end
- CLI: `curl -N http://localhost:8765/events` for live tail during a run
- The `--mode continue` human approval gap becomes observable without polling

### Security
## Security Analysis: Real-Time Notification Mechanism

### Threat Model

The core attack surface here is **inter-process communication between agents and the orchestrator**. The notification channel becomes a trust boundary — any mechanism that accepts input from agents must validate that input before acting on it.

---

### Critical Threats by Mechanism

#### File-Based Signals (e.g., sentinel files / inotify)
**Threat: Path Traversal / Signal Injection**
- An agent could write a signal file to an unexpected path if filenames include agent-controlled content (e.g., task IDs, agent names).
- The CLAUDE.md already calls out path sanitization — this is exactly where it matters. Signal filenames must be derived from a controlled namespace (UUIDs generated by the orchestrator, not agents).
- **Verdict:** Safest for this local, single-host architecture if paths are locked to a dedicated `signals/` directory with a strict allowlist pattern like `[a-f0-9-]{36}\.done`.

#### Unix Domain Sockets / Named Pipes
**Threat: Privilege confusion and spoofing**
- If multiple processes share the socket, any process with filesystem access can send notifications.
- No authentication is built in — a malicious or buggy agent could send a completion signal for a task it didn't run, causing the orchestrator to act on false state.
- **Mitigation:** Bind sockets with `0600` permissions; validate payload schema strictly (Pydantic model, not raw string eval).

#### HTTP Webhooks (local loopback)
**Threat: SSRF if URL is configurable, replay attacks**
- If agents are ever given the webhook URL as a parameter, a compromised prompt could redirect to an external host — classic SSRF.
- No TLS on loopback is acceptable, but shared-secret HMAC signing (like GitHub webhooks) is cheap and prevents spoofed completions.
- **Verdict:** Overkill for a local system; adds a network listener unnecessarily.

---

### Highest-Priority Mitigations

1. **Signal origin validation** — The orchestrator must only accept signals for task IDs it issued. Maintain an in-memory set of `pending_task_ids`; discard any signal for an unknown ID.

2. **Dedicated signal directory with restricted permissions**
   ```python
   SIGNAL_DIR = pathlib.Path("signals").resolve()
   SIGNAL_DIR.mkdir(mode=0o700, exist_ok=True)
   # Validate on read:
   assert signal_path.parent.resolve() == SIGNAL_DIR
   ```

3. **Payload schema enforcement** — Never `json.loads()` + act directly. Define a `TaskCompletionSignal(BaseModel)` with strict fields. Reject anything that doesn't parse.

4. **No subprocess-controlled data in signal paths** — Looking at `agents.py:67-69`, args are already interpolated with agent data. The same pattern in signal filenames would be dangerous.

5. **Log all signal events** — Use the existing `_log_file_lock` pattern from `agents.py:17` for any signal I/O. Unlogged notifications are an audit gap.

---

### Recommendation

**Use file-based signals with `inotify`/`watchdog`** — it's the simplest, most auditable mechanism with no new network attack surface. The security constraints are fully enumerable (directory permissions, filename pattern, payload schema). Avoid any mechanism where agents supply the notification endpoint or channel name.

## Debate Round 2: Critiques & Refinements
### Researcher
The previous round has usefully narrowed the scope to an initial single-machine implementation, reframing the "Multi-Agent System" as one with co-located components. This changes the calculus for notification mechanisms.

**Challenge: Over-reliance on File-Based Polling for Real-time**

While the Architect's proposal to write to `logs/events.jsonl` and the Security agent's lean towards `inotify`/`watchdog` are valid for auditing and basic local signaling, relying on file-based mechanisms for *real-time consumption by external observers* has significant drawbacks:

*   **Inefficiency and Latency:** Pure polling of a file (e.g., `tail -f` or repeated reads) introduces inherent latency and can be inefficient due to disk I/O, especially if the file is frequently updated by a rapid stream of agent events. While `inotify` (Linux) or similar OS-specific mechanisms improve this, they are non-portable and still require a dedicated watcher process per observer.
*   **Lack of Standard API:** A raw log file, even in JSONL format, doesn't present a standard, programmatic interface for diverse consumers. Integrating with web UIs, external dashboards, or other services becomes a bespoke parsing and watching exercise.
*   **Robustness Concerns:** Managing file rotations, ensuring atomicity across various OS types, and handling potential file corruption with concurrent writes/reads can add complexity that an event stream inherently manages.

**Support: Named Pipes + FastAPI SSE (BackendDev's Proposal)**

The BackendDev's approach—**UNIX Named Pipes (FIFO) combined with a FastAPI SSE endpoint**—provides the most robust and future-proof solution for the current single-machine context:

*   **Optimal Local IPC:** Named pipes offer highly efficient, low-latency, zero-dependency inter-process communication *on the same machine*. This addresses the "overkill" concerns for external message brokers (Redis, Kafka) without sacrificing performance for internal orchestrator-to-notifier signaling.
*   **Standardized External Interface:** Exposing events via Server-Sent Events (SSE) over HTTP is a widely adopted web standard. It allows external observers (CLI tools, web UIs, other services) to consume a real-time event stream using standard HTTP clients (e.g., `curl`, browser `EventSource` API) without requiring stateful WebSockets or custom file parsers.
*   **Decoupling and Extensibility:** This architecture neatly separates the core orchestrator's event generation from external event consumption. If the system evolves to a distributed multi-machine setup, the FastAPI SSE layer can easily be adapted to pull events from a distributed message queue (e.g., Redis Pub/Sub, Kafka) with minimal impact on event consumers.
*   **Security Integration:** The security mitigations outlined (dedicated directories, strict permissions, payload validation) are fully applicable. The named pipe itself can be permissioned (`0600`), and the FastAPI endpoint can rigorously validate incoming JSON events from the pipe before fanning them out.

**Conclusion:**

While a purely file-based log (Architect) is simple, it's not truly "real-time" for external programmatic consumption and lacks a robust interface. The BackendDev's **Named Pipes + FastAPI SSE** approach leverages the efficiency of local IPC while providing a standardized, extensible, and more consumable real-time event stream. This design best balances the immediate single-machine requirements with best practices for event-driven architecture and future scalability.

### Architect
## Architect — Round 2 Challenge

### Where the Prior Proposals Diverge (and Who's Right)

The prior Architect proposal and my `tasks.md` already reflect the correct architecture. The BackendDev's **named pipe + FastAPI SSE sidecar** proposal is the one that needs direct challenge — it introduces unnecessary complexity at the wrong layer.

---

### Challenge: BackendDev's FastAPI SSE Sidecar Is Wrong Here

BackendDev proposes adding a FastAPI process alongside the orchestrator to fan out events via SSE. This fails on three grounds:

**1. It solves a distribution problem that doesn't exist.**
The orchestrator is a CLI tool invoked as a single process. There is no "multi-machine fan-out" requirement. A sidecar HTTP server adds a port, a startup race, a teardown race, and a new failure mode (SSE server crashes, orchestrator runs blind). The cost is real; the benefit is hypothetical.

**2. Named pipes (FIFOs) are write-blocking by default.**
`open(FIFO_PATH, "w")` in BackendDev's snippet **blocks indefinitely** if no reader is attached. In a fully automated run with no human tailing the pipe, every agent completion stalls until timeout. This is a correctness bug, not a performance concern.

**3. The incremental session log flush is correct — but already captured.**
BackendDev independently re-discovered the right fix for session log persistence. It belongs in TASK-05 of the existing plan. It doesn't justify a separate sidecar.

---

### Challenge: Security's `inotify`/`watchdog` Recommendation

Security rightly flags path traversal and payload schema enforcement — both are addressed in the current tasks (locked `logs/` directory, `AgentEvent` dataclass validation). However, recommending `watchdog` (a third-party package) as the preferred mechanism contradicts the zero-dependency constraint in our Definition of Done. `inotify` is also Linux-only. The `queue.SimpleQueue` + `events.jsonl` approach is fully portable and requires no watcher.

Security's mitigations — signal origin validation, strict directory permissions, payload schema enforcement — are all valid and should be added as acceptance criteria to **TASK-03** and **TASK-05**.

---

### What the Existing Plan Gets Right

The `tasks.md` proposal is sound:
- `queue.SimpleQueue` is the correct synchronization primitive (no lock needed for put/get, unlike `queue.Queue` which has unnecessary complexity for this use case)
- Dispatcher as a daemon thread means no hanging on abnormal exit
- `emit()` non-blocking contract is the critical invariant — agent threads must never block on notification I/O
- Layered notifiers (console → file → optional webhook) scales from "dev CLI" to "CI integration" to "dashboard" without changing the core

---

### One Gap to Address: Incremental Session Log Flush

The existing plan doesn't explicitly call out moving the session log flush inside `_call_agent` (BackendDev's correct observation). Add this to **TASK-05**:

> After emitting `agent_done`/`agent_failed`, flush `session_log["rounds"]` to disk within `_log_lock`. This ensures external observers reading the JSON log see completed entries without waiting for `session_done`.

---

### Final Verdict

| Proposal | Verdict |
|---|---|
| Researcher (webhooks for everything) | Over-engineered for local tool; valid only as optional layer |
| Architect (queue + file + optional webhook) | **Correct. Proceed.** |
| BackendDev (FIFO + FastAPI SSE) | Blocking FIFO bug + unnecessary sidecar. Reject. |
| Security (inotify/watchdog) | Third-party dep violates constraints. Mitigations are valid; apply to TASK-03/05. |

The `tasks.md` is the implementation contract. TASK-05 should absorb BackendDev's incremental flush insight. TASK-03 should absorb Security's directory permission and payload validation requirements.



`tasks.md` updated with two absorbed mitigations:
1. **TASK-05** now includes BackendDev's incremental session log flush and Security's signal origin validation (`_pending_agent_keys` set).
2. **TASK-03** now enforces `mode=0o700` on log dir creation and a `resolve()`-based path traversal guard.
3. **TASK-07** adds a path traversal test case.
4. **TASK-06** notes the SSRF allowlist requirement if webhook URLs are user-configurable.

The FastAPI SSE sidecar proposal is rejected — the blocking FIFO write is a correctness bug that would stall every agent completion in unattended runs.

### Backenddev
## Challenge: The FIFO Sidecar Is Already Broken

I wrote the `notification_server.py` in Round 1. Now that it's been implemented, I need to challenge it — because the actual code has two critical defects that undermine the whole approach.

### Defect 1: `O_NONBLOCK` + `connect_read_pipe` deadlocks on reconnect

```python
# notification_server.py:34
fd = await loop.run_in_executor(None, lambda: os.open(FIFO_PATH, os.O_RDONLY | os.O_NONBLOCK))
```

Opening a read-end FIFO with `O_NONBLOCK` succeeds immediately — but `asyncio.connect_read_pipe` was not designed for non-blocking file descriptors backed by a FIFO. When the orchestrator process exits and the write-end closes, the reader gets EOF, falls through to the `except Exception`, sleeps 100ms, then tries to re-open. On Linux, re-opening a read-only FIFO with `O_NONBLOCK` **succeeds with ENXIO if no writer is attached** — so you get a tight error loop, not graceful reconnection. This will spin the event loop at 100% CPU between orchestrator sessions.

### Defect 2: The sidecar requires a running writer or the FIFO blocks

The `/events` SSE endpoint returns no data until the orchestrator actually opens and writes to the FIFO. A client connecting before `orchestrator.py` starts gets a hanging response with no keepalive. The `/health` endpoint is also useless for diagnosing this — it shows `subscribers: 1` but events are silently queued forever.

### The Architect Is Right: Drop the Sidecar

The Architect's `queue.SimpleQueue` + `events.jsonl` design solves the actual problem with zero new dependencies and zero reconnection logic. I was wrong to propose FastAPI here — it's the right tool for external-facing APIs, not in-process IPC.

**Concrete pivot:**

1. **Keep the incremental flush pattern** from `_log_cli_call` — it already writes `logs/cli_calls.log` per-event. Extend it to also append to `logs/events-{session_id}.jsonl` with the Architect's `AgentEvent` schema.

2. **Add a single dispatcher thread** drained from `queue.SimpleQueue`. Non-blocking emit in `_call_agent`, synchronous drain in the background thread. The Architect's design is implementable in ~80 lines.

3. **Delete `notification_server.py`** or gate it behind an explicit `--serve-events` flag. An optional sidecar is fine; a required one is a reliability liability.

### One Thing Security Gets Wrong

Security recommends `watchdog`/`inotify` for file watching. `watchdog` is a third-party dependency and `inotify` is Linux-only. The whole point of `events.jsonl` is that consumers can `tail -f` it with zero setup. Don't add a dependency to the observer side.

### Concession to BackendDev Round 1

The incremental session log flush I proposed is still correct and independent of the FIFO decision. `_append_session_entry` should call `_write_session_log` under the existing `_log_lock`. That's a 3-line change and the highest-value, lowest-risk improvement on the table.

**Bottom line:** Ship the Architect's in-process queue, delete the FIFO sidecar, and add incremental session log flushing. That's the complete solution.

### Security
## Security Challenge: Round 2

### Challenge 1: BackendDev's `/tmp/mas-events.fifo` is a Symlink Attack Vector

The proposed `_emit_event` uses `os.path.exists(FIFO_PATH)` then `open(FIFO_PATH, "w")` — a textbook TOCTOU race. Any local user can pre-create `/tmp/mas-events.fifo` as a symlink to an arbitrary file before the orchestrator runs:

```bash
ln -sf /home/ben/.ssh/authorized_keys /tmp/mas-events.fifo
# Orchestrator now overwrites your SSH keys with JSON events
```

`/tmp` is world-writable. **Never use `/tmp` for security-relevant IPC.** Use a directory under the project root with `0700` permissions, as the previous Security round correctly specified.

### Challenge 2: FastAPI SSE Listener Has No Authentication

BackendDev's `curl -N http://localhost:8765/events` is a feature — and a threat. Any process on the machine (including a malicious agent subprocess) can:
- Subscribe to all task completion events, leaking session IDs and agent outputs
- If the endpoint ever accepts POST requests, inject false completion signals

No auth is mentioned. Loopback ≠ safe in multi-user environments or containers with shared namespaces. This is an unnecessary attack surface for a single-process tool.

### Challenge 3: Architect's `detail` Field is an Unscoped Data Sink

The `AgentEvent.detail: Optional[str]` field with no size limit or content policy is a PII/secrets exfiltration path. Agent responses regularly contain task context — and in this domain (see CLAUDE.md: financial data), that could mean API keys, account numbers, or strategy details written verbatim to `logs/events-{session_id}.jsonl`. This file has no mention of access controls.

**Mitigation:** Strip or hash the `detail` field in `FileSignalNotifier`. Reserve it for the in-memory dispatcher only.

### What to Keep

The **Architect's in-process `queue.SimpleQueue` approach is correct** — it has zero network surface. The challenge is the persistence layer, not the queue itself.

### Concrete Requirements for the Implementation

```python
# Signal directory — project-local, not /tmp
SIGNAL_DIR = (Path(__file__).parent / "signals").resolve()
SIGNAL_DIR.mkdir(mode=0o700, exist_ok=True)

# Validate on every read — no agent-supplied path components
def _validate_signal_path(p: Path) -> bool:
    return p.parent.resolve() == SIGNAL_DIR and re.fullmatch(r"[a-f0-9-]{36}\.done", p.name)

# Payload schema — reject unknown fields
class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["agent_started", "agent_done", "agent_failed", "round_done"]
    session_id: str
    agent_key: str
    # NO detail field in persisted form
```

### Priority Order

| Risk | Severity | Fix |
|------|----------|-----|
| `/tmp` FIFO symlink attack | High | Move to project-local `signals/` dir, `0700` |
| SSE listener with no auth | Medium | Remove entirely; `tail -f events.jsonl` is sufficient |
| Unbounded `detail` in persisted events | Medium | Omit from `FileSignalNotifier`; keep in-memory only |
| No signal origin validation | High | Orchestrator tracks `pending_task_ids`; discard unknown |

The Architect's layered approach is sound. The implementation must enforce that **the orchestrator owns the event bus entirely** — agents never push directly, only the `_call_agent` wrapper emits.

## Final Synthesis & Architecture Recommendation
### Executive Summary

The project requires a real-time notification mechanism to signal agent task completion within the Multi-Agent System. After analyzing proposals for file-based signals, inter-process communication (IPC), and webhooks, the recommended solution is a lightweight, in-process event bus using Python's standard library. This approach avoids the complexity and security pitfalls of external dependencies (e.g., Redis), sidecar processes (e.g., FastAPI server), or platform-specific file watchers (`inotify`). The chosen design is robust, secure, requires zero new dependencies, and provides immediate, non-blocking feedback while persisting events to a log file for external observation.

### Recommended Tech Stack

| Component | Technology | Reasoning |
| :--- | :--- | :--- |
| **In-Process Messaging** | `queue.SimpleQueue` | A thread-safe, non-blocking, zero-dependency FIFO queue from the Python standard library. It is the ideal primitive for decoupling event producers (agent threads) from consumers (dispatcher thread) within a single process. |
| **Event Dispatch** | `threading.Thread` | A background daemon thread will be used to create a non-blocking dispatcher that drains the event queue and fans out notifications. This ensures that agent execution is never delayed by notification I/O. |
| **Event Persistence** | Newline-Delimited JSON (`.jsonl`) | Events will be written to a session-specific file (`logs/events-{session_id}.jsonl`). This format is simple, human-readable, auditable, and easily consumed by standard command-line tools like `tail -f` for real-time observation by external processes. |
| **Schema Enforcement** | Pydantic `BaseModel` | All events will be validated against a strict Pydantic model. This prevents data corruption, enforces a consistent structure, and mitigates risks from malformed event payloads. |

### Architecture Overview

The architecture is centered around a non-blocking, in-process event bus that decouples agent execution from notification delivery.

```
  Agent Execution Thread               Orchestrator Main Process
  ─────────────────────                ─────────────────────────
  _call_agent() starts
        │
        ▼
  Emits "agent_started" Event
        │
        ▼
  subprocess.run(agent)
        │
        ▼ (completes)
  Emits "agent_done" Event ──────────► queue.SimpleQueue
                                             │
                                             │ (drained by...)
                                             ▼
                                     Event Dispatcher Thread
                                             │
                                ┌────────────┴────────────┐
                                ▼                         ▼
                         FileNotifier              ConsoleNotifier
                  (writes to logs/           (prints live status
                   events-{id}.jsonl)             to terminal)
```

1.  **Event Emission:** The `orchestrator.py`'s `_call_agent` function will be the sole authority for emitting events before and after a subprocess runs. Agents themselves remain unaware of the notification system.
2.  **Queue:** A `queue.SimpleQueue` instance acts as the central, thread-safe buffer. Event emission is a fast, non-blocking `put()` operation.
3.  **Dispatcher:** A single background thread continuously drains the queue, validating each event.
4.  **Notifiers:** The dispatcher passes events to a list of registered "notifiers." The initial implementation will include:
    *   `FileNotifier`: Appends the validated event as a JSON line to a session-specific log file.
    *   `ConsoleNotifier`: (Optional) Prints live status updates to the terminal.
5.  **Incremental Log Flush:** The primary session log (`session-{id}.json`) will be flushed to disk after each agent completion, making final results available immediately.

### Key Risks & Mitigations

| Risk | Mitigation |
| :--- | :--- |
| **Path Traversal / Symlink Attack** | All event files will be written to a dedicated `logs/` directory created with restrictive `0o700` permissions. File paths will be programmatically validated to ensure they resolve within this directory, preventing writes to arbitrary locations. Using `/tmp` is explicitly forbidden. |
| **Sensitive Data Leakage** | The persisted `AgentEvent` schema will **omit** the free-form `detail` field, which could contain sensitive data from agent outputs. This field may be used for transient, in-memory operations only. |
| **Event Spoofing** | The orchestrator will maintain an in-memory set of `pending_task_ids`. The event dispatcher will validate that any `agent_done` event corresponds to an active ID before processing it, discarding any unsolicited signals. |
| **Blocking I/O Stalls** | The event emission point in the agent execution thread will only perform a non-blocking `queue.put()`. All potentially slow I/O (file writes, future webhooks) is deferred to the separate dispatcher thread. |
| **Race Conditions (TOCTOU)** | The proposal for a named pipe (`/tmp/mas-events.fifo`) was rejected due to inherent race conditions and blocking behavior. The in-process queue design eliminates this entire class of filesystem races. |

### Implementation Phases

**Phase 1: Core Event Bus and Secure Persistence**
*   **Milestone:** Define the `AgentEvent` Pydantic schema (without the `detail` field for persistence).
*   **Milestone:** Implement the `EventDispatcher`, `queue`, and background thread structure.
*   **Milestone:** Create the `FileNotifier`, ensuring it uses a permission-locked project subdirectory (`logs/`).
*   **Milestone:** Integrate `_emit_event()` calls into `orchestrator.py` and implement the incremental flush of the main session log.

**Phase 2: Live Feedback and Validation**
*   **Milestone:** Implement the `ConsoleNotifier` to provide live terminal feedback on agent status.
*   **Milestone:** Implement signal origin validation by having the dispatcher check against a set of pending task IDs.
*   **Milestone:** Add comprehensive unit and integration tests covering the event bus, notifiers, and all security mitigations.

**Phase 3: Optional Remote Notification (Future Work)**
*   **Milestone:** If required, implement a `WebhookNotifier`, gated by a configuration flag.
*   **Milestone:** Ensure the webhook implementation includes robust security, such as HMAC signature validation and a configurable allowlist for target URLs to prevent SSRF attacks.

### Open Questions & Next Steps

*   **Final `AgentEvent` Schema:** The exact fields for the Pydantic model need to be finalized before implementation. The recommended baseline is: `event_type`, `session_id`, `agent_key`, `agent_name`, `round`, `timestamp`, `status`, and `duration_s`.
*   **Log Rotation Policy:** The current session-based file naming (`events-{session_id}.jsonl`) prevents indefinite growth of a single file. A higher-level log rotation/archival strategy is out of scope for this task but should be considered in the future.
