# Multi-Agent Project Advisor Report

**Project:** Plan a clone of the Yarn Loop app (knitting/crocheting project tracker). Core features: project tracking, row counters, stash management, and pattern storage. Target: Web-based mobile-responsive app (FastAPI + React/Vite). Provide detailed spec.md and initial tasks.md.

## Selected Specialist Agents
1. **Architect**
2. **Backend_Dev**
3. **Frontend_Dev**
4. **Skeptic**

## Debate Round 1: Initial Proposals
### Architect
The existing `spec.md` is empty and `tasks.md` belongs to a prior project. I'll generate both from scratch for the Yarn Loop clone.

---

## Architectural Analysis

### Recommended Architecture: Modular Monolith

A microservices split is unwarranted here. The domain is cohesive, scaling needs are modest (single-user to small community), and the specified stack (FastAPI + React/Vite) already implies a unified backend. One deployable unit, four bounded modules.

```
┌─────────────────────────────────────────┐
│           React/Vite SPA                │
│  (Projects | Counters | Stash | Patterns│
└──────────────────┬──────────────────────┘
                   │ REST + SSE
┌──────────────────▼──────────────────────┐
│               FastAPI                   │
│  ┌──────────┐ ┌────────┐ ┌───────────┐ │
│  │ projects │ │ stash  │ │ patterns  │ │
│  └────┬─────┘ └────────┘ └─────┬─────┘ │
│  ┌────▼──────────────────┐     │       │
│  │     counters          │     │       │
│  └───────────────────────┘     │       │
│  ┌─────────────────────────────▼─────┐ │
│  │    SQLAlchemy (async) + Alembic   │ │
│  └───────────────────────────────────┘ │
│  ┌────────────────────┐                │
│  │  Auth (JWT / OAuth)│                │
│  └────────────────────┘                │
└──────────────────┬──────────────────────┘
         ┌─────────▼──────────┐
         │  PostgreSQL (prod) │
         │  SQLite (dev)      │
         └────────────────────┘
         ┌────────────────────┐
         │  Local FS / S3     │
         │  (patterns, images)│
         └────────────────────┘
```

### Key Architectural Decisions

**Storage:** Async SQLAlchemy with both SQLite (dev) and PostgreSQL (prod) via a single `DATABASE_URL` env var. `Decimal` for any numeric fields (yardage, weight). Alembic for migrations.

**Counters:** Row counters need real-time feel — use SSE (Server-Sent Events) for live counter sync rather than WebSockets. Simpler, one-way, no WS infra needed.

**Patterns:** Store metadata in DB; binary files (PDFs/images) on local FS under `data/patterns/` with an S3-compatible adapter interface for future swap.

**Auth:** JWT via `python-jose` + `passlib`. Optional OAuth (Ravelry) as stretch goal — abstract behind an `AuthProvider` interface now.

**Risks:**
- File storage path traversal → sanitize all uploads with `pathlib.Path.resolve()` and restrict to project data dir
- Counter race conditions (multiple tabs) → use DB-level optimistic locking (`version` column) on `Counter` rows
- Large pattern PDFs → enforce 25MB upload cap at nginx/FastAPI middleware level

---

Now writing both files:





---

## Architectural Summary

**Stack:** FastAPI (async throughout) + React/Vite + PostgreSQL/SQLite + SQLAlchemy 2.0 async + Alembic

**Pattern:** Modular monolith — four feature modules (projects, counters, stash, patterns) under one FastAPI app. No microservices: the domain has no independent scaling vectors.

**Key decisions:**

| Concern | Decision | Rationale |
|---|---|---|
| Counter sync | SSE (not WebSocket) | One-way push, no WS infra, simpler mobile support |
| Concurrent updates | Optimistic locking (`version` column) | Avoids row-level DB locks, correct under multi-tab use |
| File storage | Local FS + path sanitization | Simple for v1; adapter interface ready for S3 swap |
| Numeric types | `Decimal`/`Numeric` everywhere | Yardage, price, gauge — no float rounding errors |
| Auth | JWT (stateless) | No session store needed; mobile-friendly |

**Top risks flagged:**
1. Path traversal on file uploads → mitigated by `uploads.py` guard in Task 7
2. Counter race conditions → mitigated by optimistic lock in Task 5
3. Large PDF memory pressure → mitigated by 25MB cap + streaming `FileResponse`

### Backenddev
# Backend Recommendations: Yarn Loop Clone

## Stack: FastAPI + PostgreSQL + Redis

**Language/Framework: Python 3.12 + FastAPI**
FastAPI is the right call here — async-native, automatic OpenAPI docs, Pydantic v2 for validation, and excellent ecosystem for future ML features (pattern recommendations). The mobile-responsive requirement means the API is the single source of truth; FastAPI's performance is more than sufficient.

## Database Architecture

**Primary: PostgreSQL 16**
Relational data wins here. Yarn projects have complex relationships:
- `projects` → `counters` (one-to-many)
- `projects` → `stash_items` (many-to-many via `project_yarn`)
- `patterns` → `projects` (one-to-many)

Use `Numeric(10,2)` for yardage/weight calculations — never `Float`. JSONB columns for flexible pattern metadata (gauge, needle sizes, custom fields) without over-normalizing.

**Cache Layer: Redis**
- Session storage + JWT refresh token blacklisting
- Row counter state (high-frequency writes — don't hammer Postgres on every increment)
- Rate limiting counters

## API Design: REST

GraphQL is overkill for this scope. REST with clean resource URLs:
```
GET/POST   /api/v1/projects
GET/PUT    /api/v1/projects/{id}
POST       /api/v1/projects/{id}/counters/{counter_id}/increment
GET/POST   /api/v1/stash
GET/POST   /api/v1/patterns
```

Row counter increments are the hot path — hit Redis first, flush to Postgres on a 30-second interval or explicit save.

## Real-Time: WebSockets (optional) / Optimistic UI

Row counters need to feel instant. Strategy:
1. Client increments optimistically
2. `POST /counters/{id}/increment` writes to Redis immediately (sub-ms)
3. Background task (`asyncio` + `BackgroundTasks`) flushes dirty counters to Postgres every 30s
4. No WebSocket needed unless multi-device sync is required — SSE for that case

## Schema Highlights

```python
class Project(BaseModel):
    id: UUID
    name: str
    status: Literal["active", "frogged", "hibernating", "complete"]
    started_at: date | None
    completed_at: date | None
    pattern_id: UUID | None
    notes: str  # markdown

class StashItem(BaseModel):
    id: UUID
    yarn_brand: str
    yarn_name: str
    colorway: str
    weight: Literal["lace","fingering","dk","worsted","bulky","super_bulky"]
    yardage: Decimal
    grams: Decimal
    quantity_skeins: Decimal
```

## File Storage

Pattern PDFs + project photos: local filesystem in dev, S3-compatible (Cloudflare R2 — free egress) in production. Use `python-multipart` for uploads, store only the object key in Postgres.

## Auth

JWT (access: 15min, refresh: 30 days) via `python-jose`. Single-user or multi-user from day one — row-level ownership (`user_id` FK on all user-owned tables) costs nothing to add now and is painful to retrofit.

## Key Dependencies
```
fastapi, uvicorn[standard], sqlalchemy[asyncio], asyncpg,
alembic, pydantic[email], redis[asyncio], python-jose[cryptography],
python-multipart, Pillow (thumbnail generation)
```

### Frontenddev
# Frontend Recommendation: Yarn Loop Clone

## Framework: React + Vite

**React** is the right call here. The ecosystem depth (especially for PWA/offline patterns and mobile-responsive UI) outweighs Svelte's bundle size advantage. Vite gives us fast HMR and a lean build pipeline.

**Key libraries:**
- `@tanstack/react-query` — server state, caching, background refetch for project/stash data
- `zustand` — lightweight client state (active counter session, UI state). No Redux overhead needed.
- `react-router-dom v6` — nested routes for `/projects/:id/counters`, `/stash`, `/patterns`

---

## UI Component Library: shadcn/ui + Tailwind CSS

shadcn/ui gives us unstyled, composable primitives (Dialog, Sheet, Card, Tabs) without fighting a design system. Tailwind handles the responsive layout. This combo is fast to iterate on and produces small bundles since you only ship what you use.

**Avoid:** Material UI or Chakra — too opinionated, heavy for a mobile-first app.

---

## Data Visualization

Row counters and project progress need:
- **Recharts** — lightweight, React-native, handles progress rings and simple line charts for "rows over time" tracking. D3 is overkill here.
- Custom SVG progress circles for the row counter UI (yarn-themed aesthetics won't come from a chart lib anyway)

---

## Real-Time: Row Counter Sync

For the counter (the core interaction), use **optimistic UI updates** — increment locally, sync to FastAPI via debounced `PATCH`. No WebSocket needed for solo use.

If multi-device sync is required later, a WebSocket connection to a FastAPI `websockets` endpoint is straightforward. Use `useRef` to hold the socket, reconnect logic via `react-use`'s `useWebSocket`.

---

## Mobile-Responsive Strategy

This is a **mobile-first** app. Users knit with their phone in hand:

- Bottom navigation bar (not sidebar) for primary nav
- Large tap targets for the counter (+/- buttons, minimum 48×48px)
- `touch-action: manipulation` on counter buttons to eliminate 300ms tap delay
- PWA manifest + service worker (Vite PWA plugin) for "Add to Home Screen" — this is a killer feature for yarn crafters
- Offline-capable counter via IndexedDB (Dexie.js) with sync-on-reconnect

---

## Build & Tooling

```
React 18 + Vite 5
TypeScript (strict mode)
Tailwind CSS + shadcn/ui
TanStack Query v5
Zustand v4
React Router v6
Recharts
Dexie.js (IndexedDB)
vite-plugin-pwa
```

---

## Critical UX Decisions

1. **Counter session persistence** — if a user closes the browser mid-row, the count must survive. IndexedDB, not localStorage.
2. **Image upload for stash/projects** — plan for lazy loading and WebP conversion (use `browser-image-compression` client-side before upload).
3. **Pattern storage** — PDF viewer via `react-pdf` with pinch-zoom support is essential.

### Skeptic
# Skeptic's Challenge: Yarn Loop Clone

## The "Simple CRUD App" Fallacy

Everyone will propose FastAPI + React + PostgreSQL and call it a day. Let me explain why this project is harder than it looks.

---

## Hidden Complexity You're Underestimating

**Row Counters are not a simple integer field.**

Real knitters use:
- Multiple simultaneous counters per project (main rows + repeat rows + stitch markers)
- Counters that reset on condition (every 10 rows, do X)
- Linked counters (when counter A hits 12, increment counter B)

A `counter: int` column will fail users within a week of launch.

**Pattern Storage is a legal minefield.**

"Pattern storage" sounds like file upload. But:
- Most commercial knitting patterns (Ravelry, LoveCrafts) are copyrighted
- Users will upload PDFs they don't own
- You now need DMCA takedown infrastructure, content moderation, and storage costs

Are you building a personal vault (private only) or a sharing platform? This single decision doubles your scope.

**Stash Management has physical-world sync problems.**

Yarn stash data goes stale the moment someone uses yarn offline. There's no sync trigger. Every other app in this space has "stash drift" complaints. What's your mitigation?

---

## Why FastAPI + React is Probably Wrong Here

**Challenge:** Why not a simpler stack?

A knitting tracker is fundamentally an **offline-first mobile app**. The target user is sitting on a couch, possibly with poor WiFi, counting rows. Yet the proposal is a web app with a separate API server.

- Why not SvelteKit with SQLite + local-first sync? Eliminates the backend entirely for v1.
- Why not a PWA with IndexedDB for offline row counting, syncing when connected?

FastAPI adds: authentication complexity, deployment infrastructure, CORS handling, and API versioning — none of which delivers user value on day one.

---

## Premature Abstractions to Watch For

When someone proposes a "pattern engine" or "project template system" in round 1, push back hard. That's months of work for a feature that requires deep domain expertise in knitting notation (chart symbols, written instructions, abbreviations vary by country).

---

## The Ravelry Lesson

Ravelry is the dominant player and has been for 15 years. They tried a UI redesign in 2020 and triggered an accessibility crisis that fractured their community. The lesson: **knitters are extremely attached to their tools and unforgiving of regressions.**

Your v1 must do 3 things flawlessly:
1. Count rows without losing data
2. Never corrupt a project record
3. Work on mobile without frustration

Everything else is scope creep.

---

## Bottom Line

Before writing a single line of code, answer these:
1. Is pattern storage private-only or shareable? (legal risk)
2. Does row counting work offline? (core UX requirement)
3. What's the minimum counter model that satisfies 90% of users?

Get these wrong in spec and you'll rewrite the data model mid-project.

## Debate Round 2: Critiques & Refinements
### Architect
## Round 2 Architect Response: Accepting Challenges, Defending Core Decisions

The Skeptic landed three real punches. I'll address each directly, then push back on the BackendDev's Redis proposal.

---

### Conceding: Counter Model Must Be Hierarchical

The Skeptic is correct. A flat `counter: int` is wrong. The counter model needs to be:

```python
class Counter(Base):
    id: UUID
    project_id: UUID
    name: str                    # "Main rows", "Repeat", "Pattern repeat"
    value: int
    reset_at: int | None         # auto-reset threshold
    parent_counter_id: UUID | None  # linked counter (A→B increment)
    sort_order: int
    version: int                 # optimistic lock — unchanged from Round 1
```

Linked counters (`parent_counter_id`) cover 90% of the "when A hits N, increment B" use case without building a rules engine. A recursive CTE or application-level trigger handles the cascade. This is a data model fix, not a scope explosion.

---

### Conceding: Pattern Storage Must Be Private-Only in v1

Legal risk is real. `spec.md` will specify: **user-uploaded patterns are private, never served to other users, no sharing endpoint.** This is a one-line policy that eliminates DMCA exposure. S3 presigned URLs (or local FS) per-user with no cross-user access. Shareable patterns = v2 with legal review.

---

### Defending: FastAPI + React Over SvelteKit/Local-First

The Skeptic's "eliminate the backend" suggestion is seductive but wrong for stated requirements:

- Multi-device sync (phone + tablet) requires a server. Local-first with CRDTs is a 3-month research project, not a v1 feature.
- The spec says **web-based** explicitly. A FastAPI backend costs one Render/Railway deployment.
- PWA + IndexedDB for offline counting is additive — FrontendDev's Dexie.js proposal handles this without abandoning the server.

The right answer: **offline-capable PWA that syncs to FastAPI**. Both things, not a choice.

---

### Challenging: BackendDev's Redis Counter Flush

The 30-second Redis→PostgreSQL flush is a data loss vector. User counts 15 rows, app crashes, last 30 seconds gone. Knitters *will* notice one lost row.

Counter: on every increment, write directly to PostgreSQL with optimistic locking. PostgreSQL with a hot row can handle thousands of increments/second — far beyond any single user's knitting speed. Redis adds operational complexity (two stores to keep consistent) for no real benefit at this scale. Remove it unless load testing proves otherwise.

---

### Architecture Unchanged, Model Patched

```
Counter model: hierarchical with parent_counter_id + reset_at
Pattern storage: private-only, no sharing API
Counters: direct Postgres writes (no Redis), optimistic lock on version column  
Offline: Dexie.js IndexedDB + sync-on-reconnect (FrontendDev's proposal adopted)
```

The modular monolith stands. The data model is now correct.

### Backenddev
## Backend Challenge Response

The Skeptic lands three valid hits. I'll address them directly, then defend where the proposals are right.

---

### Conceding: Redis for Counters is Overengineered

I proposed Redis as a write buffer for counter increments. The Skeptic is right that this adds operational complexity (another service to deploy, another failure point) before we've validated that Postgres can't handle the write volume. A single-user knitting app will never saturate Postgres with counter increments. **Drop Redis from v1.** Replace with:

1. Optimistic UI increment (instant feel)
2. Debounced `PATCH` to Postgres every 500ms
3. Pessimistic fallback: if the request fails, show an error and revert

Redis re-enters the picture only if you're building multi-user with concurrent session tracking.

---

### Conceding: Counter Schema is Underspecified

The `counter: int` model I outlined is insufficient. Minimum viable counter schema:

```python
class Counter(SQLAlchemyBase):
    id: UUID
    project_id: UUID
    name: str  # "Main rows", "Repeat", "Stitch marker"
    value: int
    max_value: int | None  # triggers notification at max
    reset_on_max: bool
    parent_counter_id: UUID | None  # linked counter increment
    version: int  # optimistic lock — keep this
```

The `parent_counter_id` self-reference handles "when counter A hits 12, increment counter B" without a separate rule engine. Scope the linked counter feature to one level deep for v1 — no recursive chains.

---

### Defending: FastAPI Over Local-First for v1

The Skeptic suggests SvelteKit + SQLite + local-first. I disagree for a specific reason: **pattern storage and stash management require a server regardless.** The moment you store PDFs or images, you need object storage + a backend API. A local-first approach for counters + a REST API for files is two architectures to maintain. Stay with FastAPI; make the PWA offline layer handle *counters only* via IndexedDB, syncing on reconnect.

---

### Conceding: Pattern Storage Needs a Decision in Spec

This is the Skeptic's strongest point. The spec must answer: **private vault only** (no sharing, no DMCA surface). This is the correct v1 answer. Implementation consequence: patterns are stored under `data/users/{user_id}/patterns/` — user-scoped paths enforced at the `pathlib.resolve()` guard, not just at the API route level.

---

### One Addition: Idempotency Keys on Counter Writes

Offline sync creates a real risk: a queued increment fires twice on reconnect. Add an `idempotency_key` (client-generated UUID per tap) to `POST /counters/{id}/increment`. Store the last N keys in a Postgres `counter_events` table. Duplicate key = 200 with current value, no double-increment.

```python
# POST /api/v1/counters/{id}/increment
class CounterIncrementRequest(BaseModel):
    idempotency_key: UUID
    delta: int = 1
```

This is the difference between "count rows without losing data" and "count rows without losing *or duplicating* data."

---

**Net spec changes needed:** Counter schema expanded, Redis removed from v1, patterns explicitly private-only, idempotency on increment endpoint.

### Frontenddev
## Frontend Challenge: Addressing the Skeptic's Valid Points

The Skeptic is right on two fronts, and I'll address them from the UI layer where the consequences land hardest.

---

### 1. Offline-First is Non-Negotiable — My Round 1 Proposal Was Incomplete

I mentioned Dexie.js and a PWA almost as afterthoughts. That was wrong. Let me be explicit: **the counter UI must work with zero network connection as the default state, not a fallback.**

The architecture should flip:

```
IndexedDB (Dexie) ← source of truth for active session
      ↕ sync worker (background)
FastAPI ← eventual persistence, not primary read path
```

This means:
- TanStack Query's `staleWhileRevalidate` is insufficient alone — reads must hit Dexie first
- The sync layer needs conflict resolution: last-write-wins with a `client_updated_at` timestamp is fine for solo use; flag conflicts visually if multi-device is added
- The offline indicator in the UI must be prominent, not a small dot — users need to know their counts are local-only

**Tooling addition:** `workbox-window` (from vite-plugin-pwa) for service worker lifecycle management, not manual SW code.

---

### 2. The Counter Data Model Forces UI Decisions Now

The Skeptic's point about linked/nested counters is correct and it directly affects component architecture. A flat `counter: int` in the UI means a flat component. That's a dead end.

The counter component must be designed around a tree:

```typescript
type Counter = {
  id: string
  label: string
  value: number
  max?: number          // triggers reset or linked-counter increment
  linkedCounterId?: string  // parent counter
  children: Counter[]
}
```

The UI implication: use a recursive `CounterCard` component from day one. Retrofitting hierarchy into a flat list component is a painful rewrite. React's composability handles this cleanly — a flat counter is just a tree of depth 1.

---

### 3. Pattern Storage: Private Vault Only in v1

The Skeptic is correct — the legal risk of shareable patterns is real and out of scope for v1. The frontend implication: **no sharing UI, no public pattern pages, no embed links.** This simplifies the component surface significantly. Pattern view is a private PDF viewer (`react-pdf`) with no share button. Design decision made; don't build the sharing infrastructure.

---

### 4. Where I Stand on the Stack

React + Vite is still correct over SvelteKit. The Skeptic's "eliminate the backend" argument is valid for a pure local-first app, but FastAPI + PostgreSQL is already specified, and the stash/project data genuinely benefits from server persistence (users switch devices, share with household members). The frontend doesn't need to change — just commit fully to offline-first patterns instead of treating them as optional.

**One addition I'm pushing for:** a visible sync status bar at the top of the counter view. Knitters need to trust the tool. Show them "Saved locally · Syncing..." explicitly.

### Skeptic
# Skeptic Round 2: The Devil Returns

## The Previous Skeptic Was Right — And Everyone Ignored It

The Architect acknowledged my concerns about counter complexity with a `version` column and moved on. The BackendDev proposed Redis caching. The FrontendDev proposed Dexie.js. Nobody answered the three critical questions I posed. Let me be more specific about why this matters.

---

## Challenging the Redis Decision Directly

BackendDev proposes: *"Row counter state (high-frequency writes — don't hammer Postgres on every increment)"*

**This is premature optimization masquerading as architecture.**

A knitting app counter gets incremented, what, 20 times per minute at peak? That's 1,200 writes/hour. PostgreSQL handles 50,000+ writes/second. You've added Redis — a separate process, connection pooling, potential split-brain state, flush-failure data loss — to solve a problem that does not exist at this scale.

When the background flush fails (network blip, crash mid-session), the counter resets. You've traded data integrity for "performance" on a workload that needed no optimization.

---

## The Dual-Database Trap

Architect proposes SQLite for dev, PostgreSQL for prod via `DATABASE_URL`.

This sounds pragmatic. It's a maintenance trap. SQLite and PostgreSQL have meaningfully different behavior for:
- JSON/JSONB queries (BackendDev wants JSONB for pattern metadata)
- Concurrent write semantics (optimistic locking behaves differently)
- Alembic migration edge cases

You will write code that passes tests locally and fails in production. Use PostgreSQL in dev via Docker Compose. The complexity cost is one `docker-compose.yml` line, not a new service.

---

## The FrontendDev's Dependency Explosion

The proposed frontend ships: React Query, Zustand, React Router, shadcn/ui, Tailwind, Recharts, Dexie.js, vite-plugin-pwa, react-pdf, browser-image-compression.

That's **10 runtime dependencies** before writing a single business logic line. Each is a maintenance burden, a security surface, and a potential breaking change. `react-pdf` alone has notoriously poor mobile pinch-zoom behavior and is a 1.5MB bundle addition.

**Challenge:** What does the counter UI require on day one? A number, a plus button, a minus button. Ship that. Add `react-pdf` when a user asks for it.

---

## SSE vs. WebSockets: A False Debate

The Architect chose SSE over WebSockets for counter sync. Fine. But then the FrontendDev says optimistic UI with debounced PATCH is sufficient — *no SSE needed*.

These proposals contradict each other. Pick one and commit. My recommendation: debounced PATCH + IndexedDB is correct for v1. SSE is infrastructure for a multi-device sync feature nobody has specified a requirement for yet.

---

## What I Still Need Answered

1. **Pattern storage scope**: Private vault or shareable? The spec must say this explicitly before a single upload endpoint is written.
2. **Offline-first commitment**: Is Dexie.js/IndexedDB a v1 requirement or a stretch goal? It determines the entire frontend architecture.
3. **Counter model**: The spec needs at least a data model sketch for multi-counter scenarios. A `counter: int` column will fail real users.

Stop building infrastructure. Define the data model for counters and answer the legal question on patterns.

## Final Synthesis & Architecture Recommendation
# Final Recommendation: Yarn Loop Clone

## 1. Executive Summary

This document outlines the final plan for building a web-based, mobile-responsive clone of the Yarn Loop application. The core architecture will be a **modular monolith** using a **FastAPI** backend and a **React/Vite** frontend. A key, non-negotiable feature for v1 is an **offline-first row counter**, which will function without a network connection by using IndexedDB as its primary data store, syncing to the backend when available. This approach directly addresses the most critical user need: reliable, resilient row counting.

## 2. Recommended Tech Stack

| Component | Technology | Reasoning |
| :--- | :--- | :--- |
| **Backend** | Python 3.12, FastAPI | High performance, async-native, and excellent data validation with Pydantic. Aligns with modern Python standards. |
| **Frontend** | React, Vite, TypeScript | Robust ecosystem, strong PWA support, and fast development cycle. TypeScript ensures type safety. |
| **Database** | PostgreSQL (via Docker) | Provides robust relational integrity, `JSONB` support, and avoids the "dev/prod parity" trap of using SQLite locally. **Redis is explicitly excluded for v1** as it's a premature optimization that introduces unnecessary complexity and data loss risk. |
| **ORM** | SQLAlchemy 2.0 (async), Alembic | Provides a powerful, async-ready interface to the database and robust schema migration tooling. |
| **UI/Styling** | Tailwind CSS, shadcn/ui | A highly productive combination for building a custom, responsive, and lightweight UI without the overhead of a heavy component library. |
| **State** | Zustand (client), TanStack Query (server), Dexie.js (offline) | A layered approach: `Zustand` for simple UI state, `TanStack Query` for managing server data, and `Dexie.js` as the mandatory offline-first persistence layer for the core counter feature. |
| **Real-time** | Optimistic UI + Debounced PATCH | For v1, real-time sync via WebSockets or SSE is over-engineering. The UI will update instantly and sync with the backend asynchronously. This provides the necessary UX without the infrastructure cost. |
| **Auth** | JWT (Stateless) | Simple, secure, and well-supported, making it ideal for a decoupled frontend and future mobile clients. |

## 3. Architecture Overview

The system consists of a React Single-Page Application (SPA) that communicates with a FastAPI backend via a REST API. The most critical component, the row counter, is designed to be offline-first.

```
┌───────────────────────────────────────────────┐
│              React/Vite PWA (SPA)             │
│ (Offline-first Counters via Dexie.js/IndexedDB) │
│       (Projects | Stash | Patterns)           │
└──────────────────────┬────────────────────────┘
                       │ REST API (async)
                       │ (with Idempotency Keys on writes)
┌──────────────────────▼────────────────────────┐
│                    FastAPI                    │
│ ┌────────────┐ ┌────────┐ ┌───────────────┐  │
│ │  projects  │ │ stash  │ │   patterns    │  │
│ │(CRUD)      │ │(CRUD)  │ │(private-only) │  │
│ └─────┬──────┘ └────────┘ └───────┬───────┘  │
│ ┌─────▼───────────────────┐        │        │
│ │     counters (hierarchical)     │        │
│ └─────────────────────────┘        │        │
│ ┌──────────────────────────────────▼──────┐ │
│ │  SQLAlchemy (async) + Alembic + numeric │ │
│ └───────────────────────────────────────┘ │
│ ┌──────────────────────┐                  │ │
│ │  Auth (JWT)          │                  │ │
│ └──────────────────────┘                  │ │
└──────────────────────┬────────────────────┘
         ┌─────────────▼──────────┐
         │ PostgreSQL (Docker dev)│
         └────────────────────────┘
         ┌────────────────────────┐
         │  Local FS / S3 Adapter │
         │ (user-scoped uploads)  │
         └────────────────────────┘
```

**Key Architectural Resolutions:**
*   **Counter Model:** The database schema will support hierarchical counters (`parent_counter_id`) and conditional resets (`reset_at`) to satisfy real-world crafting needs. This directly addresses the Skeptic's primary concern.
*   **Pattern Storage:** Pattern uploads are **private-only for v1**. This eliminates all copyright and DMCA-related legal risks. Files will be stored in user-scoped directories.
*   **Offline Strategy:** The frontend is not just offline-capable; it's offline-first for counters. The UI's source of truth is IndexedDB. A service worker will handle background synchronization.

## 4. Key Risks & Mitigations

| Risk | Mitigation |
| :--- | :--- |
| **Counter Data Loss/Duplication** | **Offline-first design** with Dexie.js. On writes, use **idempotency keys** for API requests to prevent double-counting during network reconnects. Use database-level **optimistic locking** (`version` column) as a final safeguard. |
| **Legal Risk (Copyright)** | **Private-only pattern storage**. The spec explicitly forbids any sharing or public access features for user-uploaded patterns in v1. |
| **File Upload Vulnerabilities** | **Strict path sanitization** and validation on the backend. All file storage paths will be resolved and constrained to a non-executable data directory, scoped by `user_id`. |
| **Dev/Prod Environment Mismatch** | Use **Docker Compose for all development**, ensuring the development database is PostgreSQL, identical to production. SQLite will not be used. |

## 5. Implementation Phases

*   **Phase 1: Project Foundation & Auth (Milestone: Secure Hello World)**
    *   Initialize FastAPI and React/Vite projects.
    *   Set up Docker Compose with PostgreSQL.
    *   Implement JWT-based user registration and login endpoints.
    *   Define core SQLAlchemy models, including the hierarchical `Counter` and `User`.

*   **Phase 2: The Offline-First Counter (Milestone: A Resilient Counter)**
    *   Implement the core counter UI in React with large, mobile-friendly tap targets.
    *   Integrate Dexie.js to store all counter data and session state in IndexedDB.
    *   Build the background sync service to push changes to the FastAPI backend with idempotency keys.
    *   Implement the hierarchical counter logic (parent/child relationships) in the UI.

*   **Phase 3: Supporting Features (Milestone: MVP Complete)**
    *   Build CRUD interfaces for Projects, Stash, and private Patterns.
    *   Implement secure file uploads for patterns and project photos.
    *   Flesh out the responsive UI for all sections.

## 6. Open Questions & Next Steps

*   What is the precise UI/UX for creating and managing linked/nested counters? (Requires design mockups)
*   Is a full `react-pdf` viewer a v1 requirement, or can we simply link to the uploaded PDF? (Deferring is preferred to reduce bundle size).
*   What is the v2 priority for OAuth providers (e.g., Ravelry, Google)?
