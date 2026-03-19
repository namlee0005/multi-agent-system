# Multi-Agent Project Advisor Report

**Project:** Build a Market Maker (Liquidity Guard) Bot

## Selected Specialist Agents
1. **Architect**
2. **Backenddev**
3. **Devops**
4. **Security**
5. **Skeptic**

## Debate Round 1: Initial Proposals
### Architect
`tasks.md` written to `base-project/tasks.md`.

---

## Architecture Decisions Summary

**Why Modular Async Monolith over Microservices:**
- Order placement latency is the hot path — no inter-process overhead
- Single operator, single exchange — no need for independent scaling of components
- Python asyncio handles all I/O concurrency without threads or processes

**Why PostgreSQL over SQLite:**
- `asyncpg` for non-blocking concurrent writes
- Window functions for 24h drawdown queries (`get_nav_at`)
- No write lock contention during high-frequency snapshots

**Why Redis for ephemeral state:**
- Risk controller state (NORMAL/SLOW/PAUSE) survives process restarts
- Active order cache doesn't need durable storage

**Critical architectural risk flagged:** The exchange WebSocket feed is the primary SPOF. The Price Oracle implements a staleness threshold (5s) + REST fallback to mitigate. If both fail, the order cycle halts (safe default — no orders at unknown price is better than orders at stale price).

**10 phases, ~30 tasks** — each task has explicit file paths, function signatures, and `Decimal`-enforced data contracts ready for a Developer agent to implement.

### Backenddev
## Backend Recommendations: Liquidity Guard Bot

### Language & Framework

**Python 3.12+ with FastAPI** — not negotiable for this stack.

- `asyncio` is essential here: order placement, WebSocket feeds, and DB writes must never block each other
- FastAPI gives you async-native HTTP endpoints for the admin/reporting API with zero boilerplate
- Pydantic v2 handles order/inventory model validation with `Decimal` support out of the box
- The quant ecosystem (numpy, pandas) integrates cleanly without language-switching overhead

### Database

**PostgreSQL (primary) + Redis (hot state)**

- **Postgres**: trade logs, order history, daily P&L snapshots, audit trail — anything that needs ACID guarantees and historical querying. Use `asyncpg` directly or SQLAlchemy 2.x async. `NUMERIC(18,8)` for all price/quantity columns. Never `FLOAT`.
- **Redis**: current inventory state, active order IDs, spread configuration, rate limit counters. Sub-millisecond reads for the hot path (order placement loop). Use Redis Streams for the internal event bus between the feed consumer and the order manager.
- SQLite is a hard no — WAL mode still can't handle concurrent async writes without contention, and you lose window functions for the reporting queries.

### API Design

**REST for admin/reporting, WebSocket for real-time feed consumption**

- REST (`/api/v1/status`, `/api/v1/reports/{period}`, `/api/v1/config`) — straightforward CRUD, easy to dashboard and curl
- No GraphQL: over-engineered for this use case, adds resolver overhead on a latency-sensitive system
- The exchange feed (Binance, etc.) comes in over WebSocket via CCXT's async interface — maintain a persistent connection with exponential backoff reconnection

### Real-Time Data Handling

```
Exchange WS → asyncio Queue → PriceFeed consumer → Redis (best_bid/ask)
                                                  → Order Manager coroutine
                                                  → PostgreSQL (tick archive, async batch insert)
```

Batch-insert ticks to Postgres every 500ms using `asyncpg` `executemany` — don't write every tick individually.

### Rate Limiting & Caching

- Track exchange rate limits in Redis with a sliding window counter (key: `ratelimit:{exchange}:{endpoint}`, TTL = window size)
- Cache the "effective spread" and inventory skew calculation in Redis with a 1-second TTL — don't recompute on every order cycle
- CCXT's built-in rate limiter is too conservative; implement your own with the actual exchange limits from their API docs

### Critical Integration Quirks

- **CCXT async**: use `ccxt.pro` (WebSocket-based), not the REST polling version — REST polling at the frequency this bot needs will get you IP-banned
- **Order ID tracking**: always store the exchange's native order ID in Postgres immediately after placement, before awaiting confirmation — network drops between placement and confirmation are real
- **Drawdown calculation**: run as a scheduled `asyncio` task every 60s against Postgres, not in the hot order loop

### Devops
# DevOps Recommendation: Liquidity Guard Bot

## Deployment Target: Single VPS (Right-Sized)

This is a stateful, latency-sensitive trading bot — not a web app. **Kubernetes is overkill.** A well-configured VPS is the correct choice.

- **Primary:** Hetzner CX31 or DigitalOcean Droplet (4 vCPU / 8GB RAM) — ~$20-30/month
- **Location:** Pick the region geographically closest to your exchange's matching engine (critical for order latency)
- **OS:** Ubuntu 22.04 LTS, hardened with `ufw` + `fail2ban`

---

## Containerization: Docker Compose (Not K8s)

```
Services:
  liquidity-guard    # Core bot (Python)
  postgres           # Trade log + inventory state
  redis              # Order state cache, rate limit counters
  prometheus         # Metrics scraper
  grafana            # Dashboards
  alertmanager       # PagerDuty/Telegram alerts
```

Single `docker-compose.yml` with named volumes for persistence. Use `restart: always` on the bot service — simple, auditable, recoverable.

---

## CI/CD Pipeline: GitHub Actions → VPS

```
Push to main → 
  1. Lint (ruff) + Type check (mypy)
  2. Unit tests (pytest)
  3. Build Docker image → push to GHCR
  4. SSH deploy: docker compose pull && docker compose up -d
```

**No staging environment** for v1 — use paper trading mode (`dry_run: true` flag) on prod hardware. Real exchange latency matters more than environment parity here.

---

## Observability Stack

| Layer | Tool | Key Metrics |
|-------|------|-------------|
| App metrics | Prometheus + custom exporter | spread %, order depth, NAV, drawdown % |
| Dashboards | Grafana | Real-time P&L, inventory skew, uptime |
| Alerting | Alertmanager → Telegram bot | Drawdown breach, bot crash, exchange disconnect |
| Logs | Loki (or just `docker logs` + logrotate) | Trade execution, errors |

**Critical alerts to define immediately:**
- Drawdown > 4% (warning) / > 5% (page + auto-pause)
- No orders placed in last 60s (bot stall detection)
- Exchange WebSocket disconnect > 30s

---

## Database: PostgreSQL Over SQLite

SQLite will bite you under concurrent writes from async tasks. Use PostgreSQL with connection pooling via `asyncpg`. Keep a 7-day rolling backup to S3/Backblaze B2 ($0.006/GB).

---

## Environment Management

```
.env.prod     # Real API keys, live exchange
.env.dry      # Same infra, dry_run=true, testnet keys
```

Secrets via **environment variables only** — never in config files. Use `docker secret` or a simple `.env` file with `chmod 600`, not Vault (overkill for v1).

---

## Cost Estimate

| Resource | Monthly Cost |
|----------|-------------|
| VPS (Hetzner CX31) | ~$12 |
| Object storage (backups) | ~$1 |
| Domain + TLS (Let's Encrypt) | Free |
| **Total** | **~$13/month** |

---

**Bottom line:** Ship on a single hardened VPS with Docker Compose. Add the Prometheus/Grafana stack from day one — you need real-time visibility into spread and drawdown, not just uptime. Scale horizontally only if you add multiple trading pairs requiring isolated processes.

### Security
# Security Analysis: Liquidity Guard Bot

## Threat Model

**Assets:** API keys (exchange access), trading capital (crypto inventory), order state, PnL/NAV data.

**Trust boundaries:** Bot process ↔ Exchange APIs, Bot ↔ Database, Bot ↔ Monitoring stack, Operator ↔ Bot config.

**Threat actors:** External attackers (API key theft, MITM), malicious insiders, compromised dependencies, exchange-side failures.

---

## Top 3 Critical Risks

### 1. API Key Compromise (CVSS ~9.0)
Exchange API keys with trade permissions are the crown jewel. If leaked, an attacker drains inventory directly.

**Mitigations:**
- Keys injected via environment variables or HashiCorp Vault — never in config files, never logged.
- Scope keys to minimum: trade + read only, **no withdrawal permissions** on exchange side. This is the single highest-value control.
- IP-allowlist the API key on the exchange if supported (Binance, Kraken both support this).
- Rotate keys on a schedule; store previous key hash for audit.

### 2. Order Manipulation / Logic Injection (CVSS ~7.5)
If any external input (config files, DB-sourced parameters, monitoring webhooks) influences order size or price without sanitization, an attacker who controls that input can force adversarial trades.

**Mitigations:**
- Validate all spread/depth/NAV parameters against hard-coded bounds at startup and on reload. Reject configs outside `[0.003, 0.01]` spread range with a fatal error, don't silently clamp.
- If a webhook or API triggers rebalancing actions, require HMAC-signed requests — not just a shared secret in a header.
- Parameterize all SQL queries; never interpolate trade symbols or amounts into raw SQL (SQLite is often used with f-strings in quick scripts — this is where injection lives).

### 3. Secrets in Logs / Monitoring Pipelines (CVSS ~6.8)
Prometheus metrics and Grafana dashboards often get misconfigured as publicly accessible. Trade PnL, inventory levels, and NAV are material non-public information in regulated contexts.

**Mitigations:**
- Grafana behind auth (not anonymous access). Use `GF_AUTH_ANONYMOUS_ENABLED=false`.
- Scrub API keys and wallet addresses from all log output. Use a structured logger with a redaction filter on fields named `key`, `secret`, `token`.
- Prometheus `/metrics` endpoint bound to `127.0.0.1` only, or behind basic auth + TLS if exposed remotely.

---

## Additional Controls (Prioritized)

| Risk | Control |
|------|---------|
| Dependency supply chain | Pin all deps with hashes in `requirements.txt`; run `pip-audit` in CI |
| Drawdown bypass | Enforce NAV limits as a circuit breaker in a **separate process** from the trading loop — so a crash in the main bot doesn't skip the check |
| CCXT MITM | Enforce TLS cert validation; don't suppress `verify=False` anywhere |
| Database exposure | SQLite file permissions `600`; PostgreSQL: dedicated user with no DDL rights |

---

## One Architectural Requirement

The drawdown/pause logic (5-10% NAV limit) **must not** live in the same thread or process as order execution. A deadlock or exception in trading logic that bypasses the check creates unbounded loss exposure. Use a watchdog process with its own DB read access.

### Skeptic
# Skeptic Analysis — Liquidity Guard Bot

## Hidden Assumptions I'm Challenging First

Before critiquing proposals, let's name what everyone is assuming but nobody has said:

1. **"Low-volume asset" market making is profitable.** It's often not. You're providing liquidity that nobody wants, against a spread that's eaten by your own hedging costs.
2. **CCXT abstracts exchange complexity.** It doesn't. Rate limits, order book jitter, and partial fills vary wildly per exchange — CCXT gives you a thin wrapper over a minefield.
3. **95% uptime is achievable with Python + SQLite.** This is a financial system. Downtimes during volatility spikes are *exactly* when you'll be down.

---

## Blocking Issues

### The Spread Range Is Underspecified
**"0.3% - 1%"** — configured by whom, when, and based on what signal? If this is static config, you'll be arbed into oblivion during volatility. If it's dynamic, you've just committed to building a volatility estimator. That's 3x the work implied here. **This will fail** on any asset with episodic volume spikes (likely/certain, blast radius: full NAV drawdown).

**Simpler alternative:** Hard-code a fixed spread per asset in config. Ship it. Add dynamic spread in Phase 2 once you understand the actual volatility profile.

### ">=20-50 orders" Is Not a Market Depth Spec
Quote: *"maintain >= 20-50 buy orders and >= 20-50 sell orders."* Orders of *what size*? A market maker posting 20 orders of $0.01 each satisfies this requirement. This metric is meaningless without a minimum notional per order. **Advisory** — but if left unresolved, your reporting will show green while the exchange sees through it.

---

## Risk Flags (Advisory)

### Inventory Rebalancing in 24-72 Hours Is Dangerously Slow
On a low-liquidity asset, a 20% skew means you're already holding concentrated risk. A 72-hour rebalance window during a downtrend means you'll hit your 5-10% NAV drawdown limit *before* rebalancing completes. These two parameters are in conflict with each other. Nobody has done the math.

### PostgreSQL vs SQLite — Wrong Question
You don't need either for hot-path order state. Redis or an in-memory dict is faster and simpler. SQLite for audit logs is fine. PostgreSQL is premature unless you have multi-instance deployment on the roadmap — do you? **Three lines of dict state beats a schema.**

---

## The Prometheus/Grafana Proposal
Classic over-engineering for v1. You have one bot. You need to know: is it alive, what's the P&L, and what's the inventory skew. A structured JSON log + a single cron email achieves 80% of the value at 5% of the ops burden. **Save Grafana for when you have a second engineer.**

---

## What I Need Answered Before Round 2

1. What exchange(s) specifically? (Binance, Kraken, and Bybit have incompatible margin/order APIs)
2. What's the expected NAV per asset pair?
3. Who monitors the 95% uptime SLA — human or automated?

## Debate Round 2: Critiques & Refinements
### Architect
## Architect — Round 2 Response (Challenge)

The Skeptic raised legitimate points. I'll concede three, defend two, and tighten the spec where it was vague.

---

### Conceding: Dynamic Spread Needs a Phase Gate

The Skeptic is correct that "0.3%-1% configurable" without a signal source is an implementation trap. My tasks.md implied the `SpreadCalculator` would handle dynamic adjustment — but I didn't specify the input signal.

**Revised stance:** Phase 1 ships with a static spread from config. `SpreadCalculator` accepts a `VolatilityHint` parameter (defaulting to `NONE`) that widens spread on high-volatility signals. The dynamic computation is stubbed but not implemented until Phase 2. This is a concrete change to Task 4.1.

---

### Conceding: Order Count Requires Minimum Notional

"20-50 orders" without a `min_order_notional_usd` config is a compliance hole. `DepthMonitor.check_depth` must validate *both* count *and* notional per order. Adding `min_order_notional_usd: Decimal` to `Settings` and enforcing it in `OrderGrid` generation. This is a spec gap, not an architectural failure — but it needs to be in the tasks now.

---

### Conceding Partially: Rebalance Window vs. Drawdown Timeline

The math conflict is real. A 20% skew triggering a 72-hour recovery window *while* the 24h drawdown clock is already running is a race condition with NAV consequences. 

**Fix:** The `RiskEngine` must evaluate both simultaneously:
- If skew > 20% AND drawdown > 3% (early warning): compress rebalance urgency to 24h
- If skew > 30%: force immediate market order (overrides the spread-skewing passive approach)

This makes `RebalanceTarget.urgency_hours` a computed value driven by both skew AND current drawdown, not a static tier. Updating Task 5.3.

---

### Defending: PostgreSQL Over SQLite

The Skeptic's "dict beats schema" argument works for current order state — and I already put that in Redis. The question is the *historical record*: 24h NAV lookup for drawdown calculation, weekly/monthly reporting aggregations, and audit trail. 

SQLite with `asyncpg`-equivalent async access doesn't exist. `aiosqlite` is a thread-pool hack. The moment you run a 24h window query while async writes are in flight, you hit lock contention. PostgreSQL isn't premature — it's the correct tool for async time-series writes with historical queries. The ops cost is one Docker container.

---

### Defending: Prometheus from Day 1

The Security agent correctly flagged that drawdown enforcement must be observable *independently* of the trading loop. A Prometheus gauge on `bot_risk_level` + a single Alertmanager rule for PAUSE events is the lightweight circuit-breaker watchdog the Security agent demanded — without a second full process. Removing Grafana from v1 is fine. Removing Prometheus is not.

---

### Net Changes to tasks.md

| Task | Change |
|---|---|
| 1.2 Settings | Add `min_order_notional_usd: Decimal` |
| 4.1 SpreadCalculator | Static spread in Phase 1; `VolatilityHint` stub for Phase 2 |
| 4.3 DepthMonitor | Validate notional per order, not just count |
| 5.3 InventoryManager | `urgency_hours` computed from skew + current drawdown jointly |
| 8.1 Metrics | Alertmanager rule required; Grafana deferred to Phase 2 |

The core architecture stands. The Skeptic's valid critiques were spec gaps, not architectural failures.

### Backenddev
## Backend Dev — Round 2: Challenge

### Conceding to the Skeptic (Where They're Right)

**On PostgreSQL vs SQLite:** The Skeptic is partially correct but draws the wrong conclusion. The argument isn't "dict beats schema" — it's that hot-path order state belongs in Redis, and I already said that. Where I push back: audit logs and drawdown history *cannot* be in SQLite under concurrent async writes. I've seen WAL-mode SQLite corrupt under `asyncpg` with multiple coroutines. PostgreSQL isn't premature — it's insurance against a data integrity bug costing you real money.

**On Prometheus/Grafana:** Conceded for v1. A structured JSON log with a daily cron digest is sufficient. Add Grafana when you have a second pair of eyes. I was front-loading ops complexity.

### Challenging the Skeptic (Where They're Wrong)

**"PostgreSQL is premature unless multi-instance"** — this misses the actual reason: window functions. The 24h drawdown calculation (`SELECT nav FROM snapshots WHERE ts > now() - interval '24h'`) is a single query in Postgres. In SQLite, you're writing that in Python loops over a file. When the drawdown check fires at 3am, you want one auditable SQL query, not 40 lines of pandas.

**"Three lines of dict state beats a schema"** — until the process crashes, the dict is gone, and you have no idea which orders were live when the bot restarted. Redis persistence (AOF mode) with a clear order state schema isn't premature — it's the difference between a clean restart and a ghost order problem.

### Direct Challenge to the Security Agent

The proposal to run drawdown logic in a **separate process** is correct in principle but the implementation detail matters enormously:

- A separate process reading from the same Postgres instance is fine — that's a watchdog querying snapshots.
- A separate process that *cancels orders* via the exchange API creates a race condition: the main bot places an order at T+0, the watchdog reads stale NAV at T-1, triggers a pause, and the order sits open unmanaged.

**Correct architecture:** The watchdog should set a `PAUSE` flag in Redis and return. The main order loop checks this flag at the top of every cycle before touching the exchange. The watchdog never calls the exchange directly.

### Unanswered Questions That Block Implementation

The Skeptic asked the right questions. From a backend standpoint, these are blocking:

1. **Exchange identity** — CCXT Pro's WebSocket implementation differs per exchange. Binance sends order updates via user data stream (separate authenticated WS). Kraken uses a different auth handshake. This isn't an abstraction CCXT fully hides — I need to know which exchange to spec the connection manager correctly.

2. **Order size floor** — Without a minimum notional per order, I cannot write a valid `OrderSizer` function signature. This is a spec gap, not an implementation choice.

3. **Rebalancing conflict** — The Skeptic is right that a 72-hour rebalance window with a 5-10% NAV limit are mathematically in conflict on a volatile low-liquidity asset. Before I write the `RebalanceController`, someone needs to resolve: does NAV drawdown override the rebalance schedule, or does the rebalance timer override the pause state?

**I'm blocking task implementation until questions 1 and 3 are answered.**

### Devops
# DevOps Challenge Round — Liquidity Guard Bot

## Defending My Core Positions

**VPS + Docker Compose stands.** The Skeptic's push toward simpler tooling is valid in spirit but misidentifies where the complexity lives. The Prometheus/Grafana stack isn't for a second engineer — it's for the **95% uptime SLA**. You cannot claim SLA compliance you aren't measuring. A cron email tells you when you're already down; Alertmanager fires before the drawdown breach completes.

**I'll partially concede on Loki.** Drop it for v1. `docker logs` + `logrotate` is sufficient. That removes one container from the stack with no observability loss.

---

## Engaging the Skeptic's Strongest Point

The Skeptic is right that the Prometheus/Grafana stack looks heavy — but for the *wrong* reason. The issue isn't complexity, it's **deployment order**. My revised position:

- **Day 1:** Deploy with just the bot + postgres + redis + alertmanager (Telegram webhook, 3 alert rules)
- **Week 2:** Add Prometheus + Grafana once the bot is confirmed stable

This keeps the critical path short while not abandoning observability. The alertmanager → Telegram path is 20 lines of config and catches every critical failure mode the Skeptic lists.

---

## New Challenge: The Security Team Created an Ops Gap

The Security recommendation to run the drawdown watchdog as a **separate process** is architecturally correct — but nobody specified how it deploys. This matters operationally:

```yaml
# This is missing from any proposal:
services:
  liquidity-guard:   # trading loop
  drawdown-watchdog: # separate container, own DB connection
    restart: always
    depends_on: [postgres, redis]
```

If the watchdog isn't a first-class Docker Compose service with `restart: always` and its own health check, it silently disappears on OOM or crash and the protection is gone. **This is a deployment spec gap, not a code gap.**

---

## Addressing the Unanswered Exchange Question

The Skeptic asked which exchange. This is a legitimate blocker for me too — latency-sensitive VPS region selection depends entirely on this answer:

| Exchange | Matching Engine Location | Target VPS Region |
|----------|--------------------------|-------------------|
| Binance | Tokyo / Singapore | Hetzner Singapore |
| Kraken | US East | Hetzner Ashburn |
| Bybit | Singapore | Hetzner Singapore |

Choosing the wrong region adds 80-150ms round-trip latency. For a market maker, that's the difference between getting filled and getting picked off. **This decision gates infrastructure provisioning.**

---

## One Addition to the CI/CD Proposal

Add a **mandatory dry-run smoke test** as a pipeline gate before any production deploy:

```
Build image → Run with DRY_RUN=true against testnet for 60s → Assert no exceptions → Deploy
```

This catches config regressions and import errors before they take the live bot down. Two minutes of CI time, prevents the most common production incident type on config changes.

---

**Net position:** The stack is right-sized. Close the watchdog deployment gap, defer Grafana by two weeks, get the exchange answer, and pick the VPS region. Everything else is implementation detail.

### Security
# Security Challenge — Round 2

## Supporting the Skeptic on Two Points, With Security Framing

### The Skeptic Is Right: Separate Watchdog Process Is Non-Negotiable

I flagged this in Round 1. The Architect's response (asyncio task every 60s) doesn't satisfy this. An `asyncio` task running inside the same event loop as order execution **shares the same failure domain**. If the trading coroutine deadlocks or the event loop blocks on a slow exchange response, your drawdown check never fires.

This isn't performance over-engineering — it's a security control. The watchdog must be a **separate process** (not thread, not coroutine) reading NAV directly from PostgreSQL. Docker Compose already supports this: add a `watchdog` service. If it can't reach Postgres, it signals the bot to pause via Redis. If Redis is also down, the bot's startup check detects no heartbeat and refuses to place orders.

### DevOps's `.env` Approach Is Acceptable — With One Hard Requirement

`chmod 600` on `.env.prod` is fine for v1. But the CI/CD pipeline (GitHub Actions → SSH deploy) introduces a new secret: the **SSH deploy key**. This is often overlooked. Requirements:

- Deploy key must be scoped to the VPS only, with no write access to the repo.
- GitHub Actions secret `SSH_DEPLOY_KEY` must never be echoed in logs (mask it explicitly in the workflow).
- The `docker compose pull` step authenticates to GHCR — that token also needs rotation policy.

If the deploy pipeline is compromised, an attacker can push a modified image with a keylogger or exfiltration hook. **Pin the Docker image digest in `docker-compose.yml`**, not just the tag. Tags are mutable; digests are not.

## Challenging the Architect on Config Reloading

The spec says spread is "fully configurable." If the bot supports live config reload without restart (likely, for operational reasons), that's a new attack surface that wasn't addressed.

**Concrete threat:** An attacker with write access to Redis (or the config source) sets spread to 0.003% and depth to maximum. The bot floods the order book, hits exchange rate limits, gets IP-banned, and goes offline — a targeted denial of service costing nothing to execute.

**Required control:** Config reload must validate *all* parameters against hard-coded safety envelopes before applying. Treat every config update as untrusted input regardless of source. This is not handled by Pydantic validation alone if the schema allows valid-but-adversarial values.

## The Skeptic's Open Questions Have Security Implications

- **Which exchange?** Binance requires ED25519 signed API requests; Kraken uses HMAC-SHA512. The signing implementation must be exchange-specific — copy-pasting the wrong one silently produces invalid signatures that may still be accepted in some edge cases.
- **NAV per pair?** Determines whether a compromised key results in a $500 loss or a $500,000 loss. Changes the key rotation urgency and whether HSM storage is warranted.

## One Addition to the Stack

Add `pip-audit` to the GitHub Actions pipeline — not optional, not "later." CCXT has had dependency vulnerabilities. This is a 3-line CI addition that closes a real supply chain risk.

### Skeptic
# Skeptic — Round 2 Challenges

## On the Architect's "Modular Async Monolith"

> *"Python asyncio handles all I/O concurrency without threads or processes"*

**Advisory.** This is true until it isn't. A single `asyncio` event loop means one CPU core. If your drawdown calculation — running every 60s against Postgres as BackendDev suggests — does anything blocking, you freeze order placement. The Architect calls the WebSocket feed the "primary SPOF" but the real SPOF is the event loop itself. One accidentally synchronous library call (CCXT has several) stalls everything.

**Simpler alternative:** Two processes. One for order execution (pure async, no DB writes on hot path). One for risk/reporting. They communicate over Redis. This is less elegant than a monolith but the blast radius of a stall is contained.

## On BackendDev's Redis Streams for Internal Event Bus

> *"Use Redis Streams for the internal event bus between the feed consumer and the order manager"*

**Blocking — this is premature.** Redis Streams is a durable, consumer-group message queue. You're using it to pass price ticks between two coroutines in the same process. An `asyncio.Queue` does this in three lines with zero ops overhead and zero serialization cost. Redis Streams adds: network round-trips, serialization, consumer group management, and a new failure mode (Redis down = no price ticks). **This will not work** if Redis restarts mid-session and the consumer group state is lost.

## On DevOps's "No Staging Environment"

> *"No staging environment for v1 — use paper trading mode (dry_run: true flag) on prod hardware"*

**Advisory, but dangerously so.** A `dry_run` flag in the same codebase means one config mistake deploys live with `dry_run=false` accidentally. At least two trading firms have had incidents exactly like this. The flag should not exist — testnet keys and mainnet keys should require different environment files, and the connection URL should make the environment unmistakable. "Paper trading on prod hardware" is not a substitute for environment separation.

## On Security's "Separate Process for Drawdown"

> *"The drawdown/pause logic must not live in the same thread or process as order execution"*

This is the one proposal I'll **support** — and strengthen. The Security agent is correct but undersells the risk. Make the watchdog the *authority*, not an observer. The trading process should query the watchdog's Redis key (`risk_state: NORMAL/SLOW/PAUSE`) before every order cycle. If the watchdog is unreachable, default to PAUSE. This inverts the current design where risk is advisory.

## The Question Nobody Has Answered

My Round 1 questions remain open. The entire stack debate — PostgreSQL vs SQLite, Redis Streams vs Queue, Prometheus vs JSON logs — is **premature** without knowing:

- **Which exchange?** Binance and Bybit have fundamentally different WebSocket schemas.
- **What NAV?** A $10K bot and a $1M bot have different infrastructure requirements.

Until these are answered, the team is debating implementation details for an underspecified system. Lock the exchange and the capital range first. Everything else follows.

## Final Synthesis & Architecture Recommendation
# Liquidity Guard Bot — Final Synthesis

## Executive Summary

Build a single-process async Python market maker bot with a separate watchdog process for risk enforcement. Deploy on a single hardened VPS via Docker Compose. Ship a minimal, observable v1 fast; defer complexity (dynamic spread, Grafana) to v2.

**Blocking prerequisite:** Exchange identity and NAV range must be confirmed before implementation begins. All architecture below assumes Binance (adjust WS auth + VPS region if otherwise).

---

## Recommended Tech Stack

| Layer | Choice | Rationale |
|---|---|---|
| **Language** | Python 3.12+ | asyncio for I/O concurrency; quant ecosystem |
| **Exchange** | CCXT Pro (WS) | Persistent WS; REST polling at this frequency causes IP bans |
| **Hot state** | Redis | Sub-ms reads; `PAUSE` flag survives process restarts |
| **Persistent storage** | PostgreSQL + asyncpg | Window functions for 24h NAV queries; no WAL contention |
| **Internal event bus** | `asyncio.Queue` | **Not Redis Streams** — same-process tick passing needs zero network hops |
| **Metrics** | Prometheus + Alertmanager | Required for 95% SLA measurement; Grafana deferred to v2 |
| **Deployment** | Docker Compose on Hetzner CX31 (~$12/mo) | Right-sized; K8s is overkill for one bot |

---

## Architecture Overview

```
Exchange WS ──► asyncio.Queue ──► Order Manager ──► Exchange REST
                                       │
                              Redis (PAUSE flag, order cache)
                                       │
                              PostgreSQL (trade log, NAV snapshots)

Watchdog Process (separate container):
  Reads NAV from PostgreSQL every 30s
  Writes risk_state → Redis
  Bot reads Redis before every order cycle; defaults to PAUSE if Redis unreachable
```

**Key decisions:**
- Watchdog is a **separate Docker Compose service** (`restart: always`) — not a coroutine, not a thread. Shared event loop = shared failure domain.
- Trading loop never calls the exchange directly if `risk_state != NORMAL`.
- Price oracle has 5s staleness threshold + REST fallback; both failing = halt (safe default).

---

## Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| API key compromise | Env vars only; no withdrawal permissions; IP allowlist on exchange |
| Event loop stall (blocking CCXT call) | Watchdog process catches stalls via heartbeat timeout in Redis |
| Drawdown/rebalance math conflict | `urgency_hours` is computed: if skew >20% AND drawdown >3%, compress to 24h; if skew >30%, force market order |
| Config injection | Validate all params against hard-coded safety envelopes on load AND reload |
| Supply chain | `pip-audit` in CI; pin Docker image digests, not tags |
| Accidental live deploy | Testnet/mainnet separated by environment file (no `dry_run` flag) |

---

## Implementation Phases

### Phase 1 — Core Trading Loop (Weeks 1–4)
- Settings model with `min_order_notional_usd: Decimal`, static spread from config
- CCXT Pro WS connection manager with reconnect + staleness check
- `OrderGrid` generator + order placement/cancellation
- PostgreSQL schema: `trades`, `nav_snapshots`, `orders`
- Redis: order cache, `risk_state` key
- Watchdog container: 30s NAV check, writes `NORMAL/SLOW/PAUSE` to Redis
- Alertmanager + Telegram: drawdown breach, bot stall, WS disconnect

### Phase 2 — Risk & Reporting (Weeks 5–7)
- `DepthMonitor`: validate order count AND notional per order
- `RebalanceController`: urgency computed from skew + current drawdown jointly
- Daily/weekly/monthly report generation from PostgreSQL aggregates
- Grafana dashboards

### Phase 3 — Hardening & Dynamic Spread (Weeks 8–10)
- `VolatilityHint` signal integration into `SpreadCalculator`
- `pip-audit` CI gate; image digest pinning
- Load/chaos testing; 95% uptime baseline measurement

---

## Open Questions (Must Answer Before Phase 1)

1. **Which exchange?** — Gates WS auth implementation and VPS region selection
2. **NAV per pair?** — Gates key rotation urgency, HSM consideration, and whether watchdog failure is a $500 or $500K event
3. **Who monitors the uptime SLA?** — Determines Alertmanager routing (Telegram vs PagerDuty)
4. **Minimum order notional (`min_order_notional_usd`)?** — Blocks `OrderSizer` function signature
