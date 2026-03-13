# Tasks: OpenClaw Webhook Integration

## Objective
Integrate outbound OpenClaw webhook notifications into the `as_completed` loop of the orchestrator, fix the broken FIFO writer path, and harden the SSE server — all without blocking the agent debate pipeline.

---

## Task 1 — Create `notifier.py` with `NotificationEmitter`

**File:** `notifier.py` (new)

**Purpose:** Encapsulate all notification side-effects (FIFO write + outbound webhook POST) behind a single `.emit()` interface. Keeps orchestrator clean and makes the notifier independently testable.

**Pydantic schema:**
```python
from pydantic import BaseModel
from typing import Literal

class AgentEvent(BaseModel):
    event: Literal["agent.completed", "agent.failed"]
    session_id: str
    agent: str
    agent_key: str
    round: str
    status: Literal["success", "error", "validation_failed"]
    duration_s: float
    timestamp: str        # ISO 8601 UTC
    summary: str          # first 200 chars of response, stripped of newlines
```

**Class signature:**
```python
class NotificationEmitter:
    def __init__(
        self,
        fifo_path: str,
        webhook_url: str | None,
        webhook_secret: str | None,
        timeout_s: float = 3.0,
    ): ...

    def emit(self, event: AgentEvent) -> None:
        """Write to FIFO (sync, non-blocking) and fire webhook (background thread)."""
        ...

    def _write_fifo(self, payload: str) -> None:
        """Open FIFO O_WRONLY|O_NONBLOCK, write line, close. Silently skip if no reader."""
        ...

    def _deliver_webhook(self, payload: str) -> None:
        """POST payload to webhook URL with HMAC-SHA256 signature header. One retry."""
        ...

    def _sign(self, payload: str) -> str:
        """Return hex HMAC-SHA256 of payload using webhook_secret."""
        ...
```

**Module-level singletons:**
```python
_webhook_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook")
_http_client = httpx.Client(timeout=5.0, limits=httpx.Limits(max_connections=10))
```

**HMAC signing:**
- Header name: `X-MAS-Signature`
- Format: `sha256=<hex_digest>`
- Algorithm: `hmac.new(secret.encode(), payload.encode(), hashlib.sha256)`

**FIFO open flags:**
```python
fd = os.open(fifo_path, os.O_WRONLY | os.O_NONBLOCK)
```
Wrap in `try/except OSError` — if no reader is attached (`errno.ENXIO`), log at DEBUG and skip silently.

**Retry logic:**
```python
for attempt in range(2):
    try:
        resp = _http_client.post(url, content=payload, headers=headers, timeout=timeout_s)
        if resp.status_code < 500:
            return
    except httpx.RequestError:
        pass
    if attempt == 0:
        time.sleep(2.0)
# Log failure with domain only (never log full URL — may contain token)
```

**Logging:**
- Log webhook domain only: `urllib.parse.urlparse(url).netloc`
- Never log `webhook_url` or `webhook_secret` in full
- Use existing `_log_cli_call` pattern from orchestrator for consistency

**Dependencies to add:**
- `httpx` (likely already present; confirm in `requirements.txt`)

---

## Task 2 — Wire `NotificationEmitter` into `orchestrator.py`

**File:** `orchestrator.py`

**Changes:**

1. Import `NotificationEmitter` and `AgentEvent` from `notifier.py`

2. In `Orchestrator.__init__`, instantiate the emitter:
```python
fifo_path = os.getenv("MAS_FIFO_PATH", _default_fifo_path())
self._emitter = NotificationEmitter(
    fifo_path=fifo_path,
    webhook_url=os.getenv("OPENCLAW_WEBHOOK_URL"),
    webhook_secret=os.getenv("OPENCLAW_WEBHOOK_SECRET"),
    timeout_s=float(os.getenv("WEBHOOK_TIMEOUT_S", "3")),
)
```

3. In `_run_round`, inside the `as_completed` loop at line ~514, immediately after `results[key] = ...`:
```python
for future in as_completed(future_to_key):
    key, agent_name, response, success = future.result()
    results[key] = (agent_name, response, success)
    # Real-time notification — non-blocking
    self._emitter.emit(AgentEvent(
        event="agent.completed" if success else "agent.failed",
        session_id=self.session_id,
        agent=agent_name,
        agent_key=key,
        round=round_label,
        status="success" if success else "error",
        duration_s=0.0,  # TODO: track per-future start time
        timestamp=datetime.utcnow().isoformat() + "Z",
        summary=response[:200].replace("\n", " "),
    ))
```

4. Add `_default_fifo_path()` helper:
```python
def _default_fifo_path() -> str:
    runtime = os.getenv("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(runtime, "mas", "events.fifo")
```

**Constraint:** `emit()` must never raise. Wrap the call in `try/except Exception` with a log-only fallback inside `NotificationEmitter.emit()`.

---

## Task 3 — Fix `notification_server.py`

**File:** `notification_server.py`

### 3a — Fix FIFO path (security fix)

Replace:
```python
FIFO_PATH = "/tmp/mas-events.fifo"
```
With:
```python
def _default_fifo_path() -> str:
    runtime = os.getenv("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return os.path.join(runtime, "mas", "events.fifo")

FIFO_PATH = os.getenv("MAS_FIFO_PATH", _default_fifo_path())
```

In `_ensure_fifo()`, create the parent directory if absent:
```python
os.makedirs(os.path.dirname(FIFO_PATH), mode=0o700, exist_ok=True)
```

### 3b — Add bearer token auth to `/events`

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_bearer = HTTPBearer(auto_error=False)
_SSE_TOKEN = os.getenv("MAS_SSE_TOKEN")  # if unset, auth is disabled (dev mode)

def _verify_token(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)):
    if _SSE_TOKEN and (not creds or creds.credentials != _SSE_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
```

Apply as dependency:
```python
@app.get("/events")
async def stream_events(_, verified=Depends(_verify_token)):
```

### 3c — Remove subscriber count from `/health`

`/health` must not leak internal state to unauthenticated callers:
```python
@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## Task 4 — Environment Variable Documentation

**File:** `.env.example` (create if absent, or append)

```bash
# OpenClaw webhook integration
OPENCLAW_WEBHOOK_URL=https://hooks.openclaw.io/t/your-hook-id/...
OPENCLAW_WEBHOOK_SECRET=your-shared-secret

# SSE server auth (leave unset to disable in dev)
MAS_SSE_TOKEN=your-sse-token

# Webhook delivery timeout in seconds (default: 3)
WEBHOOK_TIMEOUT_S=3

# FIFO path override (default: $XDG_RUNTIME_DIR/mas/events.fifo)
MAS_FIFO_PATH=
```

---

## Acceptance Criteria

- [ ] When an agent future resolves in `as_completed`, a POST fires to `OPENCLAW_WEBHOOK_URL` within 100ms (non-blocking from the orchestrator's perspective)
- [ ] Webhook payload includes all `AgentEvent` fields; `summary` is truncated to 200 chars
- [ ] `X-MAS-Signature: sha256=<hmac>` header is present on every POST
- [ ] A dead webhook endpoint (connection refused, 500, timeout) does not stall or crash the debate loop
- [ ] FIFO events continue to reach SSE subscribers as before
- [ ] `GET /events` returns 401 when `MAS_SSE_TOKEN` is set and token is missing or wrong
- [ ] No webhook URL or secret appears in `logs/cli_calls.log` or session JSON logs
- [ ] FIFO is created under `$XDG_RUNTIME_DIR/mas/` not `/tmp/`

---

## Out of Scope

- Async rewrite of the orchestrator
- Message queue (Redis, RabbitMQ)
- Per-event delivery guarantees / at-least-once semantics
- OpenClaw inbound webhook verification (that is OpenClaw's responsibility)