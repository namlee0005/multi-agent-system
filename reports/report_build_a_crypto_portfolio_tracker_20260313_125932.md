# Multi-Agent Project Advisor Report

**Project:** Build a Crypto Portfolio Tracker with real-time BTC/ETH price tracking and profit/loss management.

## Selected Specialist Agents
1. **Researcher**
2. **Architect**
3. **Backend_Dev**
4. **Frontend_Dev**
5. **Security**

## Debate Round 1: Initial Proposals
### Researcher
</research_recommendations>The `research_recommendations.md` file has been created with the requested analysis.
I have completed the task and provided the research recommendations in `research_recommendations.md`.

### Architect
The spec.md is empty — working from the project description directly: **Crypto Portfolio Tracker with real-time BTC/ETH price tracking and P&L management.**

---

## Architecture Recommendation

### Verdict: Monolith with Clean Module Boundaries

For a two-asset portfolio tracker, microservices would be over-engineering. A well-structured monolith with clear internal module separation delivers speed, simplicity, and is trivially extractable later.

### Stack

- **Backend:** Node.js + Express + TypeScript
- **WebSocket:** `ws` library for real-time price push
- **Price Feed:** Binance WebSocket API (free, reliable, no auth needed for BTC/ETH)
- **Storage:** SQLite via `better-sqlite3` (zero-ops, file-based, synchronous — perfect for single-user portfolio)
- **Frontend:** React + Vite (or plain HTML/JS to minimize scope)

### Data Flow

```
Binance WS ──► PriceFeed Module ──► In-Memory Price Store
                                         │
                                         ▼
Browser ◄──── App WebSocket Server ◄─────┘
                    │
                    ▼
             REST API (CRUD)
                    │
                    ▼
              SQLite (holdings, transactions)
```

### Core Modules

| Module | Responsibility |
|--------|---------------|
| `PriceFeed` | Connect to Binance WS, normalize BTC/ETH ticks, emit events |
| `PriceStore` | In-memory latest price cache, subscriber pattern |
| `PortfolioService` | CRUD for holdings + transactions, compute P&L |
| `WebSocketServer` | Broadcast price updates to connected browsers |
| `REST API` | Portfolio endpoints (add/remove holding, view P&L) |
| `Database` | SQLite schema + query layer |

### Data Model

```
holdings:
  id, symbol (BTC|ETH), quantity, avg_buy_price, created_at

transactions:
  id, holding_id, type (BUY|SELL), quantity, price, timestamp
```

P&L computed on-the-fly: `(current_price - avg_buy_price) * quantity`

### Architectural Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Binance WS disconnect | Auto-reconnect with exponential backoff |
| Price staleness | Timestamp price ticks; surface "stale" indicator if >10s |
| Single-file SQLite contention | Synchronous `better-sqlite3` eliminates async races |
| No auth | Acceptable for local/single-user; document as out-of-scope |

### Integration Pattern

**Hybrid:** Event-driven for price updates (Binance → browser), request-response for portfolio CRUD. This matches the natural grain of the data — prices are pushed, portfolio state is queried.

---



---

**Key architectural decisions:**

1. **SQLite over Postgres** — no network hop, zero setup, synchronous driver eliminates async complexity for single-user scope
2. **Binance WS directly** — no third-party wrapper, no API key, stable free tier for BTC/ETH ticks
3. **In-memory price cache** — P&L computed on-demand from cache, not stored (avoids stale DB values)
4. **Single server process** — price feed, REST, and WS share one process; clean event-based wiring between modules

### Backenddev
# Backend Recommendations: Crypto Portfolio Tracker

## Language & Framework: Python + FastAPI

FastAPI is the right call here. Async-native, automatic OpenAPI docs, Pydantic validation for trade data, and excellent WebSocket support for real-time prices. The ecosystem (httpx, websockets, SQLAlchemy) covers every requirement cleanly.

## Database Architecture: Postgres + Redis

**Postgres** for persistent data:
- Portfolio positions, trade history, cost basis calculations
- JSONB for flexible asset metadata
- Numeric type (not float) for prices — financial precision matters
- Triggers for automatic P&L recalculation on trade inserts

**Redis** for real-time layer:
- Cache current BTC/ETH prices (5-10s TTL)
- Pub/Sub to fan out price updates to connected WebSocket clients
- Rate limit counters per user for API endpoints

No MongoDB. Crypto P&L requires ACID transactions (e.g., recording a trade and updating position atomically). Document stores make this painful.

## API Design: REST + WebSockets

**REST** for CRUD operations:
- `POST /trades` — record buy/sell
- `GET /portfolio` — current holdings with unrealized P&L
- `GET /portfolio/history` — realized P&L over time

**WebSockets** for price feeds:
- Single `/ws/prices` endpoint, clients subscribe to symbols
- Server pushes updates from Redis Pub/Sub
- Avoids polling — crypto prices move fast enough that 1s polling hammers the DB and feels stale

Skip GraphQL — overkill for a focused tracker with predictable data shapes.

## Price Data: CoinGecko (free tier) or Binance WebSocket

**Binance WebSocket stream** (`wss://stream.binance.com`) is the best option:
- Push-based, sub-100ms latency
- Free, no API key needed for public streams
- Single background task connects to Binance, writes to Redis, Redis fans out to clients

Fallback to CoinGecko REST polling every 10s if Binance stream drops. Implement reconnection with exponential backoff — Binance streams disconnect every 24h by design.

## Rate Limiting & Caching

- `slowapi` middleware: 100 req/min per authenticated user on REST endpoints
- Price endpoint responses cached in Redis; WebSocket clients never hit Postgres for prices
- Portfolio calculations cached per user, invalidated on trade insert

## Key Risk: Cost Basis Complexity

FIFO, LIFO, and average cost basis are all valid accounting methods — users will want to choose. Model this early. Retrofitting it onto a naive schema is painful. Store individual lots, not just aggregate positions.

## Stack Summary

| Concern | Choice |
|---|---|
| Framework | FastAPI |
| Primary DB | Postgres 16 |
| Cache/Pub-Sub | Redis 7 |
| Price feed | Binance WebSocket |
| Auth | JWT (python-jose) |
| Migrations | Alembic |

### Frontenddev
# Frontend Architecture Recommendation: Crypto Portfolio Tracker

## Framework: Next.js 14 (App Router)

**Why Next.js over plain React/Vite:**
- SSR for initial portfolio load (no flash of empty content)
- API routes eliminate need for a separate backend proxy for exchange APIs
- Built-in image optimization for crypto logos
- Easy deployment to Vercel with edge functions for low-latency price fetching

## State Management: Zustand + TanStack Query

**Avoid Redux** — overkill for this complexity. Instead:
- **Zustand** for portfolio state (holdings, cost basis, user preferences) — minimal boilerplate, excellent devtools
- **TanStack Query** for price data — handles caching, background refetch, stale-while-revalidate out of the box

```typescript
// Price data stays fresh automatically
const { data: prices } = useQuery({
  queryKey: ['prices', ['BTC', 'ETH']],
  queryFn: fetchPrices,
  refetchInterval: 30_000, // 30s polling fallback
  staleTime: 15_000,
})
```

## Real-Time Price Updates: WebSocket via `useWebSocket`

Use the `react-use-websocket` library wrapping a WebSocket connection to Binance or Coinbase streams. Fall back to polling with TanStack Query when WebSocket drops. Key pattern: keep WebSocket data in a Zustand slice, not React state, to avoid cascade re-renders across the portfolio table.

## Data Visualization: Recharts

**Recharts over D3** for this use case:
- React-native API, no imperative DOM manipulation
- Sufficient for P&L line charts, allocation pie charts, and sparklines
- Bundle size ~200KB — acceptable

Add **Tremor** for the dashboard card components (portfolio value, 24h change badges) — it's Tailwind-based and ships beautiful financial UI primitives out of the box.

## Component Library: shadcn/ui + Tailwind CSS

- Not a dependency — copy-paste components you own and can modify
- Pairs perfectly with Tremor for financial widgets
- Dark mode is trivial (crypto UIs universally expect it)

## Performance Considerations

- **Virtualize** the holdings table with `@tanstack/react-virtual` if portfolios exceed 50 assets
- **Memoize** P&L calculations with `useMemo` — these run on every price tick
- Use `React.memo` on chart components; price updates should only re-render the relevant ticker, not the full page

## Mobile/Responsive

Tailwind breakpoints are sufficient. Prioritize a **mobile-first** bottom-nav layout — most crypto users check portfolios on phone. Charts should degrade to sparklines on small viewports.

## Recommended Stack Summary

| Concern | Choice |
|---|---|
| Framework | Next.js 14 |
| State | Zustand + TanStack Query |
| Real-time | react-use-websocket |
| Charts | Recharts + Tremor |
| UI components | shadcn/ui + Tailwind |
| Table virtualization | @tanstack/react-virtual |

This stack is production-proven in fintech, keeps bundle size lean, and gives excellent DX for iterating on a data-heavy dashboard.

### Security
## Security Analysis: Crypto Portfolio Tracker

### Threat Model — Highest Priority Risks

**1. API Key Exposure (Critical)**

Price feeds (CoinGecko, Binance, etc.) and exchange integrations require API keys. These are the #1 target:
- Keys hardcoded in source or `.env` files committed to git — leak via GitHub
- Keys stored in plaintext in a database readable by the app process
- **Mitigation**: Secrets manager (HashiCorp Vault, AWS Secrets Manager, or at minimum `python-dotenv` with `.env` in `.gitignore`). Rotate keys on any suspected exposure. Use read-only API keys where possible — never grant withdrawal permissions to a portfolio tracker.

**2. Portfolio Data is High-Value PII (High)**

Holdings + cost basis = tax liability + theft target. An attacker who knows you hold 50 BTC knows exactly who to target.
- Encrypt portfolio data at rest (AES-256). Never store raw holdings in logs.
- Enforce user-level row isolation in queries — IDOR vulnerabilities here directly expose financial data.
- **Specific threat**: Multi-user deployments where `WHERE user_id = ?` is missing from a query.

**3. Price Feed Manipulation (High)**

If P&L calculations drive decisions, a compromised or spoofed price feed is an attack vector:
- Validate price data is within reasonable bounds (>20% deviation from last reading = reject and alert)
- Use multiple independent sources and take median, not a single feed
- Verify TLS certificates on all price API calls — no `verify=False`

**4. Injection Surfaces (Medium)**

- Ticker symbols and wallet addresses entered by users must be validated against strict allowlists (`^[A-Z]{2,10}$` for tickers, checksum validation for addresses)
- SQL injection risk if portfolio queries concatenate user-supplied asset names
- If webhook callbacks exist for price alerts, validate HMAC signatures

**5. Session & Auth (Medium)**

- JWT tokens: use short expiry (15min access, 7-day refresh). Store refresh tokens HttpOnly, Secure cookies — not localStorage.
- Rate limit auth endpoints: 5 attempts/15min with exponential backoff. Crypto accounts are brute-forced constantly.
- Add 2FA for any write operations (adding wallets, changing email)

### Deprioritize

Generic OWASP boilerplate (CSRF on pure API backends, clickjacking). Focus on the domain-specific risks above.

### Immediate Actions

1. Add `.env` to `.gitignore` before first commit
2. Audit all DB queries for missing `user_id` scoping
3. Never log portfolio balances or cost basis — log only action types

## Debate Round 2: Critiques & Refinements
### Researcher
The proposed architectures present viable paths, with strong alignment on real-time price feeds (Binance WebSocket) and modern frontend tooling (React-based frameworks). However, a critical divergence exists in backend persistence and framework choices that significantly impacts scalability and financial data integrity.

**Challenge: SQLite (Architect) vs. PostgreSQL (BackendDev)**
While SQLite offers zero-ops simplicity, the **BackendDev's proposal for PostgreSQL is far superior for a crypto portfolio tracker.**
1.  **Data Integrity:** Financial applications demand ACID compliance. PostgreSQL's robust transaction management, explicit numeric types, and JSONB support for flexible asset metadata are crucial for accurate P&L calculations and preventing data inconsistencies. SQLite, while good for simple cases, is inherently less suitable for complex relational financial data and concurrent access should the project ever expand beyond a single, local user.
2.  **Scalability:** Even if the initial scope is single-user, choosing PostgreSQL from the outset avoids a painful migration later. Its mature ecosystem and performance for structured data are well-proven. Projects like `Yfinance` (unofficial Yahoo Finance API) and `QuantConnect` (algorithmic trading platform) heavily rely on robust SQL databases for managing vast amounts of financial data.

**Support: Python/FastAPI (BackendDev) over Node.js/Express (Architect)**
Both are competent, but **FastAPI (Python) offers a slight edge for this domain.** Its async nature, combined with Pydantic for data validation, provides a more type-safe and developer-friendly experience for handling financial inputs (e.g., trade data). Python's ecosystem also inherently leans into data processing and financial modeling, offering a smoother transition if more complex analytics are introduced.

**Support: Redis for Caching/Pub-Sub (BackendDev)**
The **BackendDev's inclusion of Redis is essential.** For real-time price distribution via WebSockets, Redis Pub/Sub is a highly performant and scalable solution, preventing database overload and ensuring efficient client updates. Many high-frequency trading systems leverage similar in-memory caching for speed.

**Frontend (FrontendDev): Strong Proposal**
The **FrontendDev's choice of Next.js, Zustand, TanStack Query, Recharts, and shadcn/ui is well-justified and aligns with best practices for data-rich, interactive dashboards.** The specific inclusion of Tremor for financial UI primitives demonstrates excellent domain awareness. These technologies are production-proven in fintech applications, offering optimal performance and developer experience.

**Security Considerations (Security Agent):**
The **Security Agent's emphasis on API key protection, data encryption, and robust input validation is paramount.** Especially relevant is the point on `user_id` scoping for multi-user environments – a common vulnerability that can expose sensitive financial data.

**Consolidated Recommendation:**
Adopt the **PostgreSQL + Redis backend (BackendDev)**, implemented with **FastAPI (BackendDev)**. This provides a robust, scalable foundation for financial data. Couple this with the **Next.js-based frontend (FrontendDev)** for a modern and performant user experience. Prioritize the security measures outlined, particularly regarding data handling and API key management.

### Architect
Now I'll compose the Round 2 challenge response and generate the tasks.md.

---

## Architect — Round 2: Challenge

### Challenge 1: BackendDev's Postgres + Redis Stack is Overengineered

The BackendDev recommends Postgres + Redis for a **two-asset portfolio tracker**. This fails the complexity-to-value test:

- **Redis Pub/Sub** for fan-out to WebSocket clients is unnecessary. A single Node.js process with an in-memory event emitter handles this with zero operational overhead. Redis adds a network hop, a process to manage, and a failure point — for a use case that a `Map<clientId, WebSocket>` solves trivially.
- **Postgres** brings migrations, a running server process, and connection pooling for what is fundamentally a personal finance ledger. SQLite with `better-sqlite3` handles thousands of transactions/second synchronously with zero setup. The "ACID transactions for trade inserts" argument applies equally to SQLite — it supports full ACID with `BEGIN/COMMIT`.
- **Alembic migrations** for a two-table schema is ceremony, not engineering.

**Recommendation:** Keep SQLite + in-process event emitter. Add Postgres only if multi-user auth is in scope (it isn't yet).

### Challenge 2: FrontendDev's Next.js is the Wrong Tool

SSR is solving a problem this app doesn't have. A crypto portfolio dashboard:
- Is not indexed by search engines (it's personal/authenticated data)
- Has no meaningful "initial load" content to server-render — the real data comes via WebSocket anyway
- Does not benefit from API routes when a backend already exists

**Next.js adds:** webpack complexity, hydration overhead, server runtime cost, App Router learning curve.

**Plain React + Vite delivers:** instant HMR, static build, direct WebSocket connection, ~10x simpler deployment (serve from any CDN or the same Express server).

The `react-use-websocket` recommendation is sound. Zustand is correct. Recharts is correct. The framework choice is not.

### Challenge 3: Security's Threat Model Has Misaligned Priorities

The Security agent correctly identifies API key exposure as Critical, but then recommends HashiCorp Vault for a single-user local portfolio tracker. A `.env` file with proper `.gitignore` is the correct mitigation at this scope.

The IDOR threat (missing `WHERE user_id = ?`) is only relevant in multi-user deployments. For a local single-user tool, this is a non-issue. Flag it as a prerequisite if multi-user is ever added, not a current action item.

**Agreed with Security on:** read-only API keys, price validation bounds (>20% deviation = reject), no portfolio data in logs.

### Architectural Consensus Points

Across all proposals, the following are uncontested and correct:
- Binance WebSocket for price feed (push, free, no auth)
- Exponential backoff on reconnect
- Hybrid REST + WebSocket (CRUD vs. real-time streams)
- Financial precision (avoid float — use integer cents or Decimal)
- FIFO lot tracking from the start (BackendDev is right; retrofitting is painful)

---

Now generating `tasks.md`:



The tasks.md has been written. Here's a summary of the architectural challenges I raised and the task plan:

**Key challenges this round:**

1. **Against BackendDev's Postgres + Redis** — over-engineered for 2 assets and single-user scope. SQLite + in-process EventEmitter handle all requirements with zero ops overhead.

2. **Against FrontendDev's Next.js** — SSR solves no real problem here (authenticated personal data, no SEO, real content arrives via WebSocket anyway). React + Vite is strictly better for this use case.

3. **Against Security's Vault recommendation** — `.env` + `.gitignore` is the correct mitigation at this scope. Vault is the right call when you have teams and secret rotation requirements.

**What I agreed with:** FIFO lot tracking from day 1 (BackendDev was right), price validation bounds, no float for prices (integer cents), Binance WebSocket, Zustand + TanStack Query split.

The `tasks.md` is organized across 9 phases with specific file targets, typed interfaces, and clear rationale — enough for a developer agent to implement without ambiguity.

### Backenddev
## Round 2 Challenge: Pushing Back on Key Decisions

### SQLite is a Trap (Challenge to Architect)

The Architect's SQLite recommendation optimizes for setup time at the expense of correctness. Three concrete problems:

1. **No decimal type.** SQLite stores `NUMERIC` as IEEE 754 float. A cost basis of `0.1 + 0.2` becomes `0.30000000000000004`. For a portfolio tracker, this is not a rounding edge case — it compounds across every P&L calculation. Postgres `NUMERIC` is exact. This alone disqualifies SQLite for financial data.

2. **No concurrent writes.** The "single-user" assumption is baked in from the start. Adding a second user, a background price-logging job, or a CLI tool alongside the server will produce `SQLITE_BUSY` errors. Postgres handles this trivially.

3. **No row-level security.** Security correctly identified IDOR as high-priority. Postgres RLS lets you enforce `user_id` scoping at the DB layer, not just in application code. SQLite has no equivalent.

**Verdict:** Use Postgres. Docker compose makes setup a one-liner. SQLite's convenience doesn't survive contact with financial data requirements.

### Redis Pub/Sub is Justified, Not Over-Engineering (Support + Clarification)

The Architect implies Redis is overkill. It isn't, but the reasoning matters:

The Binance WebSocket runs in one async task. Portfolio WebSocket clients connect on separate coroutines. Without Redis Pub/Sub (or an equivalent in-process event bus), you're manually managing a list of active WebSocket connections and iterating over them on every price tick — which is exactly what Redis Pub/Sub replaces, but with reconnection handling, backpressure, and persistence built in.

If truly single-user forever, an asyncio `Queue` works. But Redis is the right default because it also decouples the price ingestion process from the API server process — critical if you ever want to run them separately.

### FrontendDev's 30s Polling Fallback is Too Slow (Challenge)

FrontendDev proposes a 30s polling fallback when WebSocket drops. BTC moves 1-2% in under a minute during volatile periods. A portfolio showing 30s stale prices during a reconnect is actively misleading.

**Fix:** 5s polling fallback maximum, with a visible "LIVE" / "DELAYED" indicator in the UI surfaced via a header or WebSocket message field (`{"price": 65420, "ts": 1710000000, "stale": false}`). The backend should stamp every price message with the source timestamp from Binance — the frontend uses that to compute staleness independently, not just connection state.

### Support Security on Cost Basis Encryption

Security is right that holdings are high-value PII. One concrete addition: don't store `avg_buy_price` as a denormalized column. Store individual lots (FIFO/LIFO/AVCO are separate accounting methods users need to choose). Average cost as a materialized column will silently produce wrong tax numbers if you ever add lot-level accounting later. Store the raw transactions; compute the cost basis on read.

**Bottom line:** Postgres is non-negotiable for financial correctness. Redis is justified. Price staleness needs explicit handling, not a silent 30s fallback.

### Frontenddev
# Frontend Challenge: Round 2

## Challenge: Drop Next.js, Use Vite + React

I'm walking back my own Round 1 recommendation. Next.js is wrong here.

**Why I was wrong:** The Architect correctly identified this as a single-user local portfolio tracker. Next.js buys you SSR and API routes — but SSR is worthless when portfolio data requires auth and can't be server-rendered meaningfully, and API routes just duplicate the FastAPI backend the BackendDev is already building. We'd be shipping a framework for features we won't use.

**Correct choice: Vite + React**
- Sub-second HMR, zero config for SPAs
- No server runtime to manage alongside FastAPI
- Smaller bundle, simpler deployment (static files served by FastAPI or nginx)

```typescript
// vite.config.ts — done
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/api': 'http://localhost:8000' } }
})
```

## Challenge: BackendDev's Redis Pub/Sub Complicates the Frontend Contract

The BackendDev proposes Redis Pub/Sub → FastAPI WebSocket → browser. This is the right architecture, but the frontend needs a stable message envelope or we'll have brittle deserialization code. Push back and demand a typed schema upfront:

```typescript
interface PriceUpdate {
  symbol: 'BTC' | 'ETH'
  price_usd: number
  timestamp_ms: number
  source: 'binance' | 'coingecko_fallback'
}
```

The `source` field matters — the Security agent rightly flagged price feed manipulation. On the frontend, we should visually flag when prices come from the fallback source (stale indicator, different badge color). Don't hide this from the user.

## Challenge: Tremor Is Unnecessary Weight

Tremor ships 47KB gzipped for components you can build with shadcn/ui primitives in an afternoon. For two assets (BTC + ETH), the "financial UI primitives" pitch is oversold. Cut it. Use shadcn/ui `Card` + `Badge` and spend the saved KB budget on Recharts.

## Challenge to Architect: "Plain HTML/JS" Is a Trap

The Architect floated plain HTML/JS to minimize scope. This is false economy. Without a component model, real-time WebSocket updates mean manual DOM patching — you'll reinvent a bad React in 200 lines of jQuery-style code. Vite + React adds maybe 2 hours of setup for months of maintainability. Don't skip it.

## What I'm Keeping From Round 1

- **Zustand + TanStack Query** — still correct, no changes
- **react-use-websocket** — solid, handles reconnection logic the Security agent flagged
- **`useMemo` on P&L** — non-negotiable; computing `(price - avg_cost) * qty` on every WebSocket tick without memoization will murder performance

## Revised Stack

| Concern | Round 1 | Round 2 |
|---|---|---|
| Framework | Next.js 14 | **Vite + React** |
| Charts | Recharts + Tremor | **Recharts only** |
| Everything else | unchanged | unchanged |

Simpler. Faster to ship. Honest about scope.

### Security
## Security Challenge: Round 2

My Round 1 analysis identified the right threat categories. The implementation proposals introduce several specific vulnerabilities that need direct challenge.

---

### Challenge 1: The Architect's "No Auth" Assumption is a Deployment Trap

> *"No auth — Acceptable for local/single-user; document as out-of-scope"*

**Reject this.** "Local-only" apps routinely get reverse-proxied, put behind ngrok for demos, or deployed to a VPS by the same developer. Building in zero auth creates a hard migration cliff later — the SQLite schema has no `user_id` column, so adding multi-user support later requires a full migration.

**Minimum viable auth:** A single static API token checked via `Authorization: Bearer` header costs ~20 lines and makes the app safe to expose. No login UI needed.

---

### Challenge 2: `python-jose` is a Known-Bad Choice

The BackendDev recommended `python-jose` for JWT. This library has multiple unfixed CVEs (including algorithm confusion attacks). The maintained fork `python-jose` hasn't seen a release in years.

**Use `PyJWT` instead** with explicit algorithm pinning:

```python
# BAD: algorithm confusion possible
jwt.decode(token, key)

# GOOD: reject anything not HS256
jwt.decode(token, key, algorithms=["HS256"])
```

Also: reject `alg: none` explicitly. This is not theoretical — it's the most common JWT exploit in the wild.

---

### Challenge 3: Redis Without Auth is a Default Misconfiguration

BackendDev's Redis pub/sub recommendation is architecturally sound, but Redis ships with **no authentication by default**. In dev this gets forgotten; in prod it becomes an open port.

**Require in implementation:**
- `requirepass` set in `redis.conf`
- Bind to `127.0.0.1` only — never `0.0.0.0`
- TLS if Redis is on a separate host

A portfolio tracker's Redis instance holds live holdings data in pub/sub channels. An unauthenticated subscriber gets real-time net worth data.

---

### Challenge 4: FrontendDev's `react-use-websocket` Lacks Origin Validation

The backend WebSocket server must validate the `Origin` header and require auth on the upgrade handshake. WebSocket connections bypass CORS — any page on any domain can initiate a WS connection to `ws://localhost:PORT`.

If the Architect's "no auth" stance is accepted, a malicious page the user visits can silently subscribe to their portfolio price feed.

**Fix:** Require the same Bearer token on the WebSocket upgrade request.

---

### One Thing I Missed in Round 1

**Numeric precision deserves stronger language.** The BackendDev mentioned Postgres `NUMERIC` type — this is non-negotiable. JavaScript `number` (IEEE 754 double) cannot represent `0.1 + 0.2` exactly. A portfolio tracker doing P&L in floats will silently miscalculate cost basis. Every financial calculation must stay in the DB layer using `NUMERIC(18, 8)` or be handled via `decimal.Decimal` in Python. Never serialize to JSON as raw float.

---

### Priority Stack Rank (Revised)

1. `PyJWT` with algorithm pinning — drop `python-jose`
2. Redis auth + bind address — before any deployment
3. Minimum static auth token — before exposing any port externally
4. WebSocket Origin + auth validation
5. `NUMERIC` types throughout — reject float for any monetary value

## Final Synthesis & Architecture Recommendation
# Final Project Recommendation: Crypto Portfolio Tracker

### 1. Executive Summary

This document outlines the final architectural plan for a real-time crypto portfolio tracker for BTC and ETH. The chosen architecture prioritizes data integrity, security, and a modern, responsive user experience. The system will be a two-part application: a Python backend using **FastAPI**, **PostgreSQL**, and **Redis** for robust data handling and real-time processing, and a JavaScript frontend using **Vite + React** for a fast, interactive single-page application (SPA). This approach provides a solid foundation for accurate financial calculations while remaining efficient to develop and deploy.

### 2. Recommended Tech Stack

| Component | Technology | Reasoning |
| :--- | :--- | :--- |
| **Backend** | **Python + FastAPI** | Chosen for its async performance, native data validation with Pydantic (critical for financial data), and strong Python data ecosystem. Superior to Node.js for type-safe financial modeling. |
| **Primary Database** | **PostgreSQL** | **Non-negotiable choice.** Unlike SQLite, Postgres provides a true `NUMERIC` data type, which is essential to prevent floating-point errors in financial calculations. Its ACID compliance and scalability are required for data integrity. |
| **Cache & Pub/Sub**| **Redis** | Used to cache real-time prices and distribute them efficiently to connected clients via a Pub/Sub pattern. This decouples the price ingestion service from the API server and avoids database load. |
| **Frontend** | **Vite + React** | A Vite-powered React SPA provides the best developer experience and performance for a data-heavy dashboard. Next.js was rejected as its primary feature (SSR) offers no benefit for this authenticated application. |
| **Real-time Comms**| **WebSockets** | Binance WebSocket API for price ingestion; a FastAPI WebSocket for pushing updates to the browser. This is more efficient than polling. |
| **Frontend State** | **Zustand + TanStack Query** | A modern, lightweight combination. Zustand manages global UI state, while TanStack Query handles server state, caching, and polling fallbacks. |
| **UI Components** | **shadcn/ui + Tailwind CSS** | Provides a highly customizable, modern design system without adding heavy dependencies. |
| **Charting** | **Recharts** | A declarative, React-friendly charting library sufficient for displaying P&L history and portfolio allocation. |

### 3. Architecture Overview

The system is composed of a decoupled backend and frontend.

```
                                  ┌───────────────────┐
                                  │   Browser (SPA)   │
                                  │  (Vite + React)   │
                                  └─────────┬─────────┘
                                            │ (WebSocket for Prices)
                                            │ (REST for Portfolio)
                                            ▼
┌────────────────┐      ┌───────────────────┴───────────────────┐      ┌──────────────┐
│ Binance        │      │                 Backend               │      │              │
│ WebSocket Feed ├─────►│ Price Ingestor ─► Redis (Pub/Sub) ◄───┤◄─────┤  PostgreSQL  │
│ (BTC/ETH Ticks)│      │ (FastAPI)        │ ▲                  │      │ (Portfolio,   │
└────────────────┘      │                  │ │ (Prices)         │      │ Transactions)│
                        │                  ▼ │                  │      │              │
                        │ API & WS Server ───┘                  │      └──────────────┘
                        │ (FastAPI)                             │
                        └───────────────────────────────────────┘
```

1.  **Price Ingestion**: A background service connects to the Binance WebSocket, receives price ticks, validates them, and publishes them to a Redis channel.
2.  **API & WebSocket Server**: The main FastAPI application serves a REST API for portfolio CRUD operations (persisted in PostgreSQL) and a WebSocket endpoint for clients. This endpoint subscribes to the Redis price channel and pushes updates to connected browsers.
3.  **Frontend**: A static React SPA (built with Vite) connects to the backend via REST for initial portfolio data and opens a WebSocket to receive live price updates, re-rendering components as data changes.

### 4. Key Risks & Mitigations

| Risk | Mitigation |
| :--- | :--- |
| **Financial Data Inaccuracy** | All monetary values will be stored as `NUMERIC` in PostgreSQL and handled with Python's `Decimal` type to avoid floating-point errors. Store individual transaction lots, not averaged values. |
| **Insecure by Default** | A **static bearer token** will be required for all API and WebSocket connections. **Redis will be configured with a password** and bound to localhost. The JWT library will be `PyJWT` with explicit algorithm checks. |
| **Price Feed Manipulation/Staleness** | The backend will validate incoming prices against a reasonable deviation (>20% change rejected). The frontend will receive a timestamp with each price and display a "Delayed" indicator if data is more than 5 seconds old. |
| **Credential Exposure** | All API keys and secrets will be managed via `.env` files, with `.env` included in `.gitignore` from the first commit. |

### 5. Implementation Phases

*   **Phase 1: Backend & Database Foundation**
    *   Set up Docker Compose with PostgreSQL and Redis services.
    *   Initialize FastAPI project, create DB models using `NUMERIC` types, and configure Alembic for migrations.
    *   Implement a simple, static bearer token authentication scheme.
    *   Build REST endpoints for portfolio and transaction CRUD, ensuring individual lots are stored.

*   **Phase 2: Real-Time Data Pipeline**
    *   Create a background service to connect to the Binance WebSocket.
    *   Implement Redis publishing for incoming price ticks.
    *   Build the FastAPI WebSocket endpoint to subscribe to Redis and broadcast price updates to authorized clients.

*   **Phase 3: Frontend Implementation**
    *   Initialize a Vite + React project with Tailwind CSS.
    *   Build UI components using shadcn/ui.
    *   Use `react-use-websocket` to connect to the backend and update a Zustand store with live prices.
    *   Display portfolio and P&L, memoizing calculations to ensure performance.
    *   Add a simple P&L chart using Recharts.

### 6. Open Questions

*   **Cost-Basis Method**: Which accounting method (FIFO, LIFO, Average Cost) should be implemented first? *Recommendation: Start with Average Cost for simplicity, but design the schema to support lot-based methods (FIFO) later.*
*   **User Management**: Is there a future requirement for multi-user support? *Recommendation: The static token provides a basic security layer, but a full user model would require significant changes.*
