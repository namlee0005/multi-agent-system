# Multi-Agent Project Advisor Report

**Project:** Refine the notification design: Integrate with OpenClaw Hooks/Webhooks. Leverage the Orchestrator's existing thread-listening mechanism (as_completed) to trigger an OpenClaw notification (via curl to a webhook or a workspace hook) the moment an agent finishes. Goal: Real-time updates from the Python backend directly to the user's messaging channel.

## Selected Specialist Agents
1. **Architect**
2. **Backend_Dev**
3. **Security**
4. **Devops**

## Debate Round 1: Initial Proposals
### Architect
Now I have full context. Let me provide my architectural analysis and generate `tasks.md`.

---

## Architect Analysis — OpenClaw Webhook Integration

### Current State Audit

The existing system has two relevant mechanisms:

1. **`orchestrator.py:509-515`** — `as_completed` loop in `_run_round()` — this is the exact hook point where agent completions surface
2. **`notification_server.py`** — FastAPI SSE server reading from `/tmp/mas-events.fifo`, but **the orchestrator never writes to it** — the FIFO pipe is wired on one end only

### Proposed Architecture

```
┌─────────────────────────────────────────────────┐
│  Orchestrator._run_round()                       │
│                                                  │
│  ThreadPoolExecutor                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Agent A  │  │ Agent B  │  │ Agent C  │      │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘      │
│       └─────────────┴─────────────┘             │
│               as_completed()                     │
│                    │                             │
│          NotificationEmitter.emit(event)         │
│                ┌───┴───────────┐                 │
│                │               │                 │
│          FIFO write      HTTP POST (async)       │
│                │               │                 │
│         SSE Server      OpenClaw Webhook         │
│         /events             endpoint             │
│                │               │                 │
│          Browser SSE    Messaging Channel        │
└─────────────────────────────────────────────────┘
```

### Key Architectural Decisions

**1. Single `NotificationEmitter` class** — encapsulates both emission paths (FIFO + webhook). This avoids scattering notification logic across the orchestrator and keeps the `as_completed` hook clean: one call, two side effects.

**2. Fire-and-forget webhook** — webhook POST must not block the `as_completed` loop. Use `threading.Thread(daemon=True)` or a background `ThreadPoolExecutor` with a short timeout (3s). If it fails, log and continue — notifications are best-effort.

**3. Shared event schema** — both FIFO and webhook emit the same JSON payload:
```json
{
  "session_id": "...",
  "round": "Round 1 — Proposals",
  "agent": "Architect",
  "status": "success|error|validation_failed",
  "duration_s": 4.2,
  "timestamp": "2026-03-13T..."
}
```

**4. Config via env var** — `OPENCLAW_WEBHOOK_URL` — zero friction, no config file changes needed. If unset, webhook path is silently skipped.

**5. FIFO write stays synchronous** — it's a local kernel buffer write, sub-millisecond. No need to background it.

### Risks

- **FIFO blocking**: if no reader is attached, FIFO open can block. The existing `notification_server.py` handles this with `O_NONBLOCK` on read, but the **writer** also needs `O_NONBLOCK | O_WRONLY` or a try/except to avoid hanging the orchestrator thread.
- **Webhook latency**: slow OpenClaw endpoint could pile up background threads across many agents. Cap the executor at 4 workers.
- **Secret exposure**: webhook URL may contain auth tokens — never log it, only log the domain.

---



---

**Recommendation:** The integration is a narrow, well-contained change. The `as_completed` loop at `orchestrator.py:513` is the single correct hook point — it fires exactly once per agent completion, in real time, regardless of success or failure. The `NotificationEmitter` keeps all notification concerns out of the orchestrator's core logic. Estimated scope: ~150 lines of new code, ~20 lines changed in `orchestrator.py`.

### Backenddev
## Backend Recommendations: OpenClaw Webhook Integration

### Current Architecture Assessment

The existing stack is well-suited for this integration:
- **`orchestrator.py`** already has the perfect hook point: `as_completed` at `orchestrator.py:513`
- **`notification_server.py`** is a FastAPI SSE relay fed by a FIFO — functional but adds an unnecessary hop for outbound webhooks
- The `_call_agent` return at `orchestrator.py:411` gives us `(key, agent_name, response, success)` — exactly what a webhook payload needs

---

### Recommended Design

**Language/Runtime:** Stay in Python. No separate service needed — fire webhooks directly from the orchestrator thread pool.

**HTTP Client:** `httpx` with `AsyncClient` is the right call here. But since `_run_round` is synchronous (ThreadPoolExecutor), use `httpx` in sync mode with a shared `httpx.Client` instance (thread-safe for concurrent requests). Don't reach for `requests` — no connection pooling, no timeout control.

**Webhook dispatch pattern:** Fire-and-forget with bounded retry. The notification must not block the orchestrator's main pipeline. The right shape:

```python
# Non-blocking: submit to a background ThreadPoolExecutor
# Never await inline — agent latency should not be coupled to webhook delivery
_webhook_executor.submit(_deliver_webhook, payload)
```

**Payload schema:** Standardize on this structure for all OpenClaw hook events:

```python
{
  "event": "agent.completed",        # or "agent.failed"
  "session_id": str,
  "agent": str,
  "agent_key": str,
  "round": str,
  "status": "success" | "error" | "validation_failed",
  "duration_s": float,
  "timestamp": str,                   # ISO 8601 UTC
  "summary": str                      # first 200 chars of response
}
```

**Retry strategy:** Single retry with 2s backoff, 5s timeout per attempt. Webhook failures must be logged (`_log_cli_call` compatible) but never raise — a dead webhook endpoint cannot abort an agent debate.

---

### Integration Point

The cleanest insertion is inside `_run_round` at `orchestrator.py:513-515`, immediately after `future.result()`:

```python
for future in as_completed(future_to_key):
    key, agent_name, response, success = future.result()
    results[key] = (agent_name, response, success)
    # ← dispatch webhook here, non-blocking
    self._notify_webhook(key, agent_name, success, response)
```

This fires the instant each future resolves — true real-time, not batched at round end.

---

### FIFO/SSE Server: Keep or Kill?

**Keep it** for browser/dashboard consumers (SSE is perfect for that). **Add webhooks alongside** — they serve different consumers. The FIFO writer should also emit to the webhook dispatcher. Both can coexist by having `_notify_webhook` write to both the FIFO and the outbound HTTP call.

---

### Rate Limiting / Reliability

- Single shared `httpx.Client` with `limits=httpx.Limits(max_connections=10)` — prevents webhook storms on large agent pools
- Webhook URL configurable via `config.yaml` under a `notifications.webhook_url` key — no hardcoded URLs
- HMAC-SHA256 signature on the `X-MAS-Signature` header using a shared secret — OpenClaw needs to verify authenticity

---

### What to Avoid

- **Don't use `asyncio.run()` inside threads** — the orchestrator is sync-threaded, not async. `httpx` sync client is cleaner than bridging event loops.
- **Don't block `as_completed`** waiting for webhook ACK — that collapses your parallelism advantage entirely.
- **Don't rely on the FIFO** as the sole notification path — it breaks if the SSE server isn't running.

### Security
# Security Analysis: OpenClaw Webhook Integration

## Critical Threat Surface

### 1. Webhook Secret & Authentication (HIGH — P0)

The most immediate risk is **unauthenticated webhook delivery**. If the orchestrator fires `curl` calls to an OpenClaw endpoint with no HMAC signature or bearer token, two attacks become trivial:

- **Spoofing inbound events**: Any process that can write to `/tmp/mas-events.fifo` can inject fabricated agent-completion events, causing the notification chain to deliver false data to your messaging channel.
- **SSRF via misconfigured webhook URL**: If the webhook URL is sourced from config or environment without validation, an attacker with config write access can redirect `curl` calls to internal network endpoints.

**Mitigation**: Sign every outbound webhook payload with `HMAC-SHA256` using a shared secret. Validate the URL is an allowlisted domain before any `curl` execution.

### 2. FIFO Path Hijacking (HIGH — P0)

`FIFO_PATH = "/tmp/mas-events.fifo"` is the data source for all notifications. `/tmp` is world-writable. Attack vector:

- An adversary pre-creates `/tmp/mas-events.fifo` as a **symlink** to a sensitive file or a regular file containing malicious JSON before the server starts.
- The `stat.S_ISFIFO` check in `_ensure_fifo()` partially mitigates this, but only **if the server starts first**. A TOCTOU race exists between `os.path.exists()` and `os.stat()`.

**Mitigation**: Create the FIFO in a process-owned directory (e.g., `/run/user/$UID/mas/`), not `/tmp`. Use `O_NOFOLLOW` when opening, and set restrictive permissions (`0o600`).

### 3. SSE Endpoint — No Authentication (MEDIUM — P1)

`GET /events` is completely open. Anyone on the network receives all agent output in real time, including potentially sensitive synthesis content, model responses, and system paths. The `/health` endpoint also leaks subscriber count.

**Mitigation**: Add a static token check via `Authorization: Bearer <token>` header. Even a simple shared secret via environment variable is acceptable for this use case.

### 4. JSON Injection via Agent Output (MEDIUM — P1)

Agent responses are truncated and written to `logs/cli_calls.log` and session logs without sanitization. If an agent response contains `}\n{"injected": true`, it can corrupt JSONL logs. More critically, if agent output feeds into the webhook `curl` payload without escaping, it enables **JSON injection** into the outbound webhook body.

**Mitigation**: Always serialize via `json.dumps()` — never string-interpolate agent responses into JSON payloads. This is already done for SSE (`json.dumps(event)`), but must be enforced end-to-end in the webhook path.

### 5. Webhook URL Exposure in Logs (LOW — P2)

When the orchestrator logs `curl` commands or webhook URLs to `logs/cli_calls.log`, any embedded tokens in the URL (e.g., `https://hooks.openclaw.io/t/SECRET_TOKEN/...`) will appear in plaintext in the log file. Session logs are also written to disk without encryption.

**Mitigation**: Redact webhook URLs in logs. Pass secrets via `Authorization` header, not URL path.

---

## Priority Order

| # | Risk | Likelihood | Impact |
|---|------|-----------|--------|
| 1 | FIFO hijack / symlink attack | Medium | High |
| 2 | Unauthenticated SSE endpoint | High | Medium |
| 3 | Missing webhook HMAC signing | Medium | High |
| 4 | JSON injection in curl payload | Low | Medium |
| 5 | Token leakage in logs | High | Low |

The FIFO and webhook authentication issues are the only ones that could result in **data exfiltration or remote spoofing**. Address those before shipping the integration.

### Devops
---

## DevOps Analysis: OpenClaw Webhook Integration

### Current Architecture Assessment

The existing notification path is sound but incomplete for outbound webhooks:

- `notification_server.py` handles **inbound** SSE subscribers (browser/local clients)
- The FIFO (`/tmp/mas-events.fifo`) is the inter-process bridge from orchestrator → SSE server
- `orchestrator.py:513` already has the ideal hook point — the `as_completed` loop where each agent future resolves

The gap: nothing fires an outbound HTTP webhook to OpenClaw at that moment.

---

### Recommended Architecture

**Do not add a separate webhook service.** The orchestrator should fire webhooks directly from the `as_completed` loop using a fire-and-forget thread. Keep it simple — this is a single-process Python app, not a distributed system.

```
as_completed loop resolves
        │
        ├─► write to FIFO  (existing SSE path — keep)
        └─► _notify_webhook(event)  (new — non-blocking, daemon thread)
                │
                └─► POST {agent, status, summary} → OPENCLAW_WEBHOOK_URL
```

**Transport:** `curl` subprocess or `httpx` async call. Use `httpx` — it's already a common dependency and avoids subprocess overhead. Fire on a daemon thread so webhook latency never blocks the debate loop.

**Auth:** HMAC-SHA256 signature header (`X-MAS-Signature`) over the JSON body, keyed by `OPENCLAW_WEBHOOK_SECRET`. OpenClaw verifies on receipt. This is the standard pattern (GitHub, Stripe, etc.).

**Retry:** One retry with 2s backoff. No queue, no Redis. If the webhook fails twice, log it and move on — agent debate must not stall waiting for a notification.

---

### Environment & Config

```bash
# .env additions
OPENCLAW_WEBHOOK_URL=https://hooks.openclaw.io/...
OPENCLAW_WEBHOOK_SECRET=<shared-secret>
WEBHOOK_TIMEOUT_S=3
```

Load via `os.getenv` — no new config file needed, the existing `config.yml` pattern is fine for agent config but secrets stay in env.

---

### What NOT to Do

- **No separate microservice** for webhook dispatch — overkill for a single-machine debug tool
- **No message queue** (RabbitMQ, Redis Streams) — adds ops burden with zero benefit at this scale
- **No async rewrite of the orchestrator** — the `ThreadPoolExecutor` model works; adding `asyncio` here would be a large, risky refactor

---

### Deployment Note

If this system ever moves to Docker, the FIFO path (`/tmp/mas-events.fifo`) must become a shared volume mount between the orchestrator and notification server containers. Add that to the `docker-compose.yml` before it becomes a bug:

```yaml
volumes:
  - mas-events:/tmp
```

---

**Bottom line:** ~40 lines of code in `orchestrator.py` — a `_notify_webhook` helper called directly inside the `as_completed` loop. No new services, no new dependencies beyond `httpx`.

## Debate Round 2: Critiques & Refinements
### Architect
## Architect — Round 2 Challenge

### Where the Prior Proposals Align (and Are Right)

All four agents converge on: `as_completed` at `orchestrator.py:513` as the hook, fire-and-forget threading, HMAC-SHA256 signing, `httpx` sync client. That consensus is correct. No need to re-litigate.

---

### Challenges

**1. The FIFO writer is still missing — and nobody tasked it.**

Every proposal discusses the FIFO as if the orchestrator already writes to it. It does not. `notification_server.py` reads from `/tmp/mas-events.fifo`, but there is zero code in `orchestrator.py` that opens or writes to that path. The SSE path is **dead end-to-end** right now. Any tasks.md that doesn't explicitly include "add FIFO writer to orchestrator" is incomplete.

**2. BackendDev's "method on Orchestrator" shape couples concerns unnecessarily.**

BackendDev proposes `self._notify_webhook(...)` as an Orchestrator method. DevOps echoes this. I maintain the `NotificationEmitter` class from Round 1 — and I want to be more specific about *why*: the Orchestrator already mixes session management, agent dispatch, synthesis, and logging. Adding webhook dispatch to that class makes it untestable in isolation. A `NotificationEmitter` with a single `.emit(event: dict)` interface can be instantiated with a mock in tests, configured independently, and swapped. The Orchestrator should hold a reference and call `.emit()` — one line.

**3. Config source conflict: resolve it definitively.**

BackendDev says `config.yaml` under `notifications.webhook_url`. DevOps says `.env`. These conflict. The correct answer: **env vars only for anything containing secrets**. `OPENCLAW_WEBHOOK_URL` and `OPENCLAW_WEBHOOK_SECRET` belong in env, not in `config.yaml` which is checked into git. `config.yaml` should only store non-sensitive behavioral config (timeout, retry count). Don't add secrets to `config.yaml`.

**4. `httpx` sync client must be module-level, not instance-level.**

BackendDev says shared `httpx.Client` — correct, it is thread-safe. But if it's instantiated per-`Orchestrator` instance, it leaks open connections across test runs. It should be a **module-level singleton** in `notifier.py`, initialized once at import time. The executor should also be module-level with a fixed `max_workers=4`.

**5. Security's FIFO path fix needs a concrete path, not a principle.**

Security correctly flags `/tmp` as dangerous. The concrete fix: use `os.getenv("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")` as the base directory. That directory is user-owned, not world-writable. One line of change in `notification_server.py`.

---

### Revised Scope Summary

| Component | Change Type | Lines |
|-----------|-------------|-------|
| `notifier.py` (new) | `NotificationEmitter` class, FIFO writer + webhook dispatch | ~90 |
| `orchestrator.py` | Instantiate emitter, call `.emit()` in `as_completed` | ~10 |
| `notification_server.py` | Fix FIFO path, add bearer token auth on `/events` | ~15 |

Total: ~115 lines. The BackendDev/DevOps ~40-line estimate **only** covers the webhook half and ignores the broken FIFO writer.

---



The `tasks.md` has been written. Key challenges summarized:

1. **The FIFO writer is missing** — all prior proposals treated it as existing; it doesn't. Tasked explicitly.
2. **`NotificationEmitter` over inline method** — separation of concerns and testability win.
3. **Env vars for secrets, not `config.yaml`** — resolves the BackendDev/DevOps conflict.
4. **Module-level `httpx.Client` singleton** — prevents connection leaks across Orchestrator instances.
5. **`/health` leaks subscriber count** — Security missed this; fixed in Task 3c.

### Backenddev
## Backend Dev — Round 2 Challenge

### Where the Previous Proposals Agree (and Are Right)

The Architect, DevOps, and my own Round 1 proposal converge on the same hook point (`orchestrator.py:513`), the same transport (`httpx` sync client), and fire-and-forget threading. That consensus is correct. Don't challenge it.

---

### Challenge 1: The FIFO Is a Dead End — Stop Routing Through It

Every proposal treats the FIFO as a first-class notification path that webhooks should write alongside. **It shouldn't.** Look at `notification_server.py:34`: the FIFO is opened `O_NONBLOCK` on the **read** side. But the orchestrator's **write** side is never opened — the orchestrator currently writes nothing to the FIFO. The Security agent correctly flagged the TOCTOU race on `/tmp`.

My challenge: **skip the FIFO entirely for webhook dispatch.** The `_notify_webhook` call in `as_completed` should write directly to the background executor. The FIFO/SSE path is a separate concern for browser clients and should remain independently wired — or killed — without coupling it to outbound webhook reliability. Two separate call sites in `as_completed`:

```python
self._fifo_emit(event)      # best-effort, local SSE subscribers
self._notify_webhook(event) # best-effort, outbound OpenClaw
```

Coupling them inside a single `NotificationEmitter` (Architect's proposal) creates a class whose failure modes are entangled. A blocked FIFO write shouldn't affect webhook delivery and vice versa.

---

### Challenge 2: `config.yaml` for Webhook URL Is Wrong

DevOps says "secrets stay in env." My Round 1 proposal contradicted itself by suggesting `config.yaml` for the webhook URL. The BackendDev's own previous recommendation to use `config.yaml` is wrong — webhook URLs frequently contain embedded tokens (e.g., `https://hooks.openclaw.io/t/SECRET/...`). Config files get committed. `os.getenv("OPENCLAW_WEBHOOK_URL")` only. If unset, skip silently. No config file changes.

---

### Challenge 3: HMAC Signing Is Necessary, But Scope It Correctly

Security flagged HMAC as P0. I agree — but the right implementation detail is often skipped: **sign the serialized bytes, not the dict.** Serialize first, sign second, send both:

```python
body = json.dumps(payload, separators=(",", ":")).encode()
sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
headers = {"X-MAS-Signature": f"sha256={sig}", "Content-Type": "application/json"}
client.post(url, content=body, headers=headers, timeout=5.0)
```

If you sign the dict and re-serialize, key ordering can differ and signature verification breaks.

---

### What the Proposals Miss

**Session timing.** The `as_completed` loop doesn't currently capture `start_time` per agent. The `duration_s` in the proposed payload schema will always be wrong unless a `time.perf_counter()` snapshot is stored when each future is **submitted** (line 510), not when it completes. This is a one-line fix at submission time but all four proposals overlooked it entirely.

---

### Net Verdict

Sound direction across all proposals. The two concrete corrections: decouple FIFO from webhook dispatch, and capture agent start times at `executor.submit()` time. Everything else is implementation detail.

### Security
## Security Challenge — Round 2

The proposals are directionally correct and show real security awareness. But three specific gaps need direct challenges before this ships.

---

### Challenge 1: HMAC Is Proposed But Not Specified — This Will Get Implemented Wrong

Both BackendDev and DevOps say "HMAC-SHA256 on `X-MAS-Signature`" as if it's solved. It isn't. Underspecified HMAC leads to broken implementations every time. The exact contract must be:

```
HMAC-SHA256(key=OPENCLAW_WEBHOOK_SECRET, msg=raw_bytes_of_request_body)
```

Where `msg` is the **exact bytes POSTed**, not a re-serialized Python dict. If the implementation signs `json.dumps(payload)` but the body is serialized again by `httpx`, the signature will be computed over different bytes than what's transmitted, making it unverifiable. Specify the signing contract precisely:

```python
body_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
sig = hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
headers['X-MAS-Signature'] = f'sha256={sig}'
# POST body_bytes directly — do not re-encode
```

---

### Challenge 2: The `summary` Field Is a Data Exfiltration Vector

BackendDev's payload schema includes:
```json
"summary": "first 200 chars of response"
```

Agent responses can contain session state, file paths, model reasoning about sensitive config, or partial key material from the debate context. Sending truncated agent output to an **external** webhook endpoint — even a legitimate one — is a data boundary violation. The webhook recipient (OpenClaw) receives internal agent content they have no need for.

**Recommendation:** Strip `summary` from the outbound webhook payload entirely. Status + agent name + duration is sufficient for a real-time notification. If richer content is needed, the receiver can poll the SSE endpoint or the session log via an authenticated API. Don't push content you don't need to push.

---

### Challenge 3: SSRF Validation Is Still Underspecified

The Architect flags SSRF risk, I flagged it in Round 1, but nobody has specified what "allowlisted domain" validation actually means in code. `os.getenv('OPENCLAW_WEBHOOK_URL')` with no validation is the current implicit plan. This needs an explicit guard:

```python
from urllib.parse import urlparse

ALLOWED_SCHEMES = {'https'}
BLOCKED_HOSTS = {'localhost', '127.0.0.1', '0.0.0.0', '169.254.169.254'}

def _validate_webhook_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in ALLOWED_SCHEMES
        and parsed.hostname not in BLOCKED_HOSTS
        and not parsed.hostname.startswith('10.')
        and not parsed.hostname.startswith('192.168.')
    )
```

This blocks cloud metadata endpoint abuse (`169.254.169.254`) and internal network redirects. Validate once at startup, fail fast, log a warning (without logging the URL value).

---

### What I Support

- Fire-and-forget on daemon thread: correct, don't block `as_completed`
- Move FIFO out of `/tmp`: strong support, `/run/user/$UID/mas/` is the right call
- `httpx` sync client over `requests`: agreed
- Secrets via env vars, not config files: agreed

The proposals are solid. Nail down the HMAC contract, drop the `summary` field, and add the SSRF guard. Those three are the difference between a secure integration and an insecure one that looks secure.

### Devops
## DevOps Challenge — Round 2

### Supporting: Fire-and-Forget + httpx Sync

All three proposals converge on `httpx` sync client + daemon thread. That's correct. Resist any pressure to introduce `asyncio` here — the orchestrator's `ThreadPoolExecutor` model is sync all the way down. Bridging event loops mid-thread is a footgun that causes intermittent deadlocks under load.

---

### Challenging: "One Retry with 2s Backoff" — Too Aggressive for the Wrong Reasons

BackendDev and my Round 1 proposal both recommend a single retry with 2s backoff. I'm pulling that back.

**The problem:** 2s backoff + 5s timeout = up to **7 seconds per webhook attempt** before giving up. With 6 agents per round running in parallel via `ThreadPoolExecutor`, you can accumulate 6 background threads each waiting up to 7s. That's acceptable — until the orchestrator hits a slow round and queues another 6. The daemon thread pool for webhooks needs an explicit `max_workers=4` cap and a **queue depth limit** (use `ThreadPoolExecutor` with a `BoundedSemaphore` or just discard if the pool is saturated).

**Revised retry rule:** 1 retry, 1s backoff, 3s timeout. Notifications are best-effort delivery. The debate loop's latency budget is more important than webhook delivery guarantees.

---

### Challenging: FIFO in /tmp — Security Raised This, DevOps Owns the Fix

Security flagged FIFO path hijacking correctly (P0). But the mitigation isn't just `O_NOFOLLOW` — it's an **ops decision**:

Move the FIFO to `/run/user/$UID/mas/events.fifo`. This is the XDG-compliant location for user runtime files on Linux, tmpfs-backed, mode `0700` by default, owned by the user. Zero code complexity, eliminates the attack surface entirely.

If containerized: mount a `tmpfs` volume at `/run/mas/` in `docker-compose.yml` and share it between orchestrator and notification server containers. `/tmp` shared volumes are a foot-in-the-door for container escape via TOCTOU.

---

### Challenging: No Observability on Webhook Failures

All proposals say "log and move on." That's insufficient. If OpenClaw is silently dropping webhooks, the user won't know until they notice their messaging channel went quiet. Add a simple counter:

```python
_webhook_failures = 0  # module-level, thread-safe via GIL for int ops
```

Emit this to the session JSON log at round end: `"webhook_failures": N`. One line in `_run_round`. Zero new dependencies. Now failures are visible in the session log without adding a monitoring stack.

---

### What Stays Solid

- `NotificationEmitter` class encapsulating both paths — clean separation, Architect got this right
- HMAC-SHA256 on `X-MAS-Signature` — non-negotiable, keep it
- Env vars only for secrets — no config file changes
- No separate microservice — this is a single-machine tool, keep it that way

---

**Net verdict:** The architecture is sound. Tighten the timeout budget, cap the webhook thread pool, move the FIFO out of `/tmp`, and add one failure counter to the session log. That's the delta between "good enough" and "production-safe."

## Final Synthesis & Architecture Recommendation
# Project Synthesis: OpenClaw Webhook Integration

## 1. Executive Summary

This document outlines the final plan to integrate a real-time notification system with OpenClaw via webhooks. The core of the design is to leverage the existing `as_completed` loop within the `Orchestrator` to trigger a non-blocking HTTP POST to a configured webhook endpoint the moment each agent completes its task. This provides immediate, real-time feedback.

The synthesis of agent proposals revealed several critical gaps in the current system, namely an insecure and non-functional FIFO-based SSE notification path, and potential security vulnerabilities in the proposed webhook design. This plan addresses both the original request and these discovered issues, resulting in a robust, secure, and decoupled notification architecture. A new, dedicated `NotificationEmitter` class will be created to handle all notification concerns, cleanly separating this logic from the core orchestrator.

## 2. Recommended Tech Stack

| Technology | Choice | Reasoning |
| :--- | :--- | :--- |
| **HTTP Client** | `httpx` (Sync Client) | **Consensus.** It is thread-safe, offers superior connection pooling, and provides fine-grained timeout control compared to `requests` or `curl` subprocesses. |
| **Concurrency** | `ThreadPoolExecutor` | **Consensus.** A fire-and-forget approach using a small, capped pool of daemon threads is essential to prevent webhook latency from blocking the main agent debate loop. |
| **Authentication** | `hmac` + `hashlib` | **Consensus.** Standard library HMAC-SHA256 is the correct, secure choice for signing webhook payloads and verifying their authenticity, as recommended by all agents. |
| **Configuration** | Environment Variables | **Consensus.** `OPENCLAW_WEBHOOK_URL` and `OPENCLAW_WEBHOOK_SECRET` must be sourced from the environment, not from version-controlled files like `config.yaml`, to prevent secret leakage. |

## 3. Architecture Overview

The architecture introduces a new `notifier.py` module containing a `NotificationEmitter` class. The Orchestrator will instantiate this class and make a single call to its `.emit()` method from within the `as_completed` loop. The emitter will then handle two distinct, parallel operations: writing to the FIFO for the local SSE server and dispatching the webhook to the external OpenClaw endpoint.

```
┌───────────────────────────────────────────┐
│        Orchestrator._run_round()          │
│                                           │
│ for future in as_completed(futures):      │
│     result = future.result()              │
│     emitter.emit(result) ◀────────────────┼─── 1. Single call from Orchestrator
└───────────────────────────────────────────┘
                 │
┌────────────────┴──────────────────────────┐
│           notifier.NotificationEmitter    │
│                                           │
│ def emit(event):                          │
│     self._write_to_fifo(event)            │
│     self._dispatch_webhook(event)         │
│       │                  │                │
└───────┼──────────────────┼────────────────┘
        │                  │
2. Fix & Use FIFO          │ 3. Dispatch Webhook (Non-Blocking)
        │                  │
┌───────▼──────────┐   ┌───▼──────────────────────────┐
│ /run/user/$UID/  │   │   ThreadPoolExecutor         │
│ mas/events.fifo  │   │   (max_workers=4)            │
└───────┬──────────┘   │     │                        │
        │              │     ▼                        │
┌───────▼──────────┐   │   httpx.post(url, ...)       │
│ notification_    │   │   (3s timeout, 1 retry)      │
│ server.py (SSE)  │   └──────────────────────────────┘
└──────────────────┘
```

## 4. Key Risks & Mitigations

| Risk | Mitigation Strategy |
| :--- | :--- |
| **SSRF via Webhook URL** | **Implement an explicit URL validator.** As specified by the Security agent, the URL will be parsed and checked against a blocklist of local/internal network addresses and restricted to `https` schemes before any request is made. |
| **Data Exfiltration** | **Strip sensitive fields from the payload.** The webhook payload will *not* contain the `summary` field or any other free-form agent output. The event will only include metadata: `agent_name`, `status`, `duration_s`, `round`, and `session_id`. |
| **Insecure HMAC Signing** | **Sign the exact raw request body.** The HMAC signature will be computed on the UTF-8 encoded, minified JSON byte string that is sent as the POST body, preventing re-serialization mismatches. The signature will be sent in an `X-MAS-Signature` header. |
| **Insecure FIFO Path** | **Move the FIFO to a user-owned directory.** The FIFO path will be changed from `/tmp/mas-events.fifo` to a secure, XDG-compliant path like `/run/user/$UID/mas/events.fifo`, mitigating the symlink attack vector. |
| **Webhook Latency/Failure** | **Use a capped, fire-and-forget thread pool.** A `ThreadPoolExecutor` with `max_workers=4`, a tight request timeout of 3 seconds, and a single retry will prevent slow or failing webhooks from impacting orchestrator performance. A failure counter will be added to session logs for observability. |
| **Unauthenticated SSE**| **Add bearer token authentication.** The `/events` endpoint on the `notification_server.py` will be protected by a simple, static bearer token checked via the `Authorization` header. |

## 5. Implementation Phases

**Phase 1: Build the `NotificationEmitter` Foundation**
- Create a new file `notifier.py`.
- Implement the `NotificationEmitter` class.
- Add module-level singletons for the `httpx.Client` and `ThreadPoolExecutor(max_workers=4)`.
- Implement the secure webhook URL validation function and the precise HMAC signing logic within a private method.
- Create the public `emit` method and a placeholder `_dispatch_webhook` method that uses the executor to call the signing and posting logic.

**Phase 2: Integrate Webhooks into the Orchestrator**
- In `orchestrator.py`, import and instantiate the `NotificationEmitter`.
- In the `_run_round`'s `as_completed` loop, add the call to `emitter.emit()`.
- Capture `start_time` when agent futures are submitted to accurately calculate `duration_s`.
- Add a `webhook_failures` counter to the orchestrator and log its value at the end of each session.

**Phase 3: Secure and Repair the SSE Notification Path**
- In `notifier.py`, implement the `_write_to_fifo` method, ensuring it uses the new secure path (`/run/user/$UID/mas/events.fifo`) and opens the FIFO with `O_WRONLY | O_NONBLOCK`.
- In `notification_server.py`, update the `FIFO_PATH` to the new secure location.
- In `notification_server.py`, add a bearer token check to the `/events` endpoint, configured via an environment variable.

## 6. Open Questions

All major architectural and security questions have been resolved through the debate rounds. The path to implementation is clear.
