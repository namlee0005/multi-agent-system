# Multi-Agent Project Advisor Report

**Project:** Refine the Yarn Loop Clone plan: Change the Frontend stack from Web to Native Mobile App (iOS/Android). Focus on React Native. Ensure the architecture supports a dedicated mobile experience with offline row counters and pattern viewing. Update spec.md and tasks.md accordingly.

## Selected Specialist Agents
1. **Architect**
2. **Frontend_Dev**
3. **Backend_Dev**
4. **Researcher**
5. **Devops**

## Debate Round 1: Initial Proposals
### Architect
Good. The `base-project/spec.md` and `tasks.md` are both empty — I'll write them from scratch, migrating the Web plan to React Native.

---

## Architect Round 1 Analysis: Web → React Native Migration

### Core Architecture Decision: React Native Modular Monolith

The previous web architecture was sound — keep the **FastAPI backend unchanged**. The entire pivot is in the client layer: replace React/Vite (PWA) with **React Native + Expo** (bare workflow). This eliminates the browser sandbox and unlocks true native offline persistence, background sync, and haptic feedback for counters.

```
┌─────────────────────────────────────────────────┐
│         React Native App (iOS + Android)        │
│  Expo SDK 51 | expo-router (file-based nav)     │
│                                                 │
│  ┌──────────────┐  ┌──────────┐  ┌──────────┐  │
│  │  Counter     │  │ Projects │  │ Patterns │  │
│  │  (offline)   │  │  (CRUD)  │  │ (viewer) │  │
│  └──────┬───────┘  └────┬─────┘  └────┬─────┘  │
│         │               │             │         │
│  ┌──────▼───────────────▼─────────────▼──────┐  │
│  │   SQLite (WatermelonDB) — offline-first   │  │
│  └──────────────────────┬────────────────────┘  │
│                         │ background sync       │
└─────────────────────────┼───────────────────────┘
                          │ REST (JWT Bearer)
┌─────────────────────────▼───────────────────────┐
│                    FastAPI                      │
│  projects | counters | stash | patterns (auth) │
│  SQLAlchemy async + Alembic + Numeric types     │
└─────────────────────────┬───────────────────────┘
               ┌──────────▼──────────┐
               │  PostgreSQL (prod)  │
               │  Docker Compose     │
               └─────────────────────┘
               ┌─────────────────────┐
               │  S3 / Local FS      │
               │  (user-scoped PDFs) │
               └─────────────────────┘
```

### Key Migration Decisions

| Concern | Web (old) | React Native (new) | Rationale |
|---|---|---|---|
| Offline storage | Dexie.js / IndexedDB | **WatermelonDB** (SQLite) | Relational offline DB, built for RN, lazy-loaded, handles hierarchical counters |
| Navigation | React Router v6 | **expo-router** (file-based) | Native stack/tab navigation, deep linking, iOS back-gesture |
| Pattern viewing | react-pdf (browser) | **react-native-pdf** | Native PDF render, pinch-zoom via native gesture handler |
| UI components | shadcn/ui + Tailwind | **NativeWind + @gluestack-ui** | Tailwind syntax on RN, accessible native primitives |
| Haptics | N/A | **expo-haptics** | Critical for counter UX — tactile feedback on increment |
| File storage | Local FS / S3 | **expo-file-system + S3** | Downloads PDFs to device, offline pattern viewing |
| Push notifications | N/A | **expo-notifications** | Optional: "your counter reached row 50" milestone alerts |
| Auth tokens | localStorage | **expo-secure-store** | OS keychain-backed, not readable by other apps |
| State | Zustand + TanStack Query | **Zustand + TanStack Query** | Unchanged — both are RN-compatible |

### Offline Architecture (Non-Negotiable)

The Skeptic's critique from Round 1 is even more relevant on mobile: users knit in spotty WiFi. WatermelonDB is the right answer over Dexie because:

1. **Relational** — counter hierarchy (`parent_counter_id`) maps naturally to SQL
2. **Lazy loading** — does not load the whole DB into memory; critical for older phones
3. **Background sync** via `expo-background-fetch` — syncs every 15 min even when app is backgrounded
4. **Idempotency keys** carried forward from the previous design — prevents double-increment on reconnect

```
User taps [+] on counter
    ↓
WatermelonDB write (sync, <1ms) → UI re-renders immediately
    ↓ (background)
Sync worker: POST /counters/{id}/increment
  { idempotency_key: uuid, delta: 1 }
    ↓
FastAPI: check counter_events table → write or dedupe
```

### Pattern Viewing Architecture

PDFs must be downloadable for offline viewing — this is a first-class feature on mobile:

```
Pattern PDF Upload
  → FastAPI stores at data/users/{uid}/patterns/{pid}.pdf
  → Returns presigned URL (or direct endpoint with JWT)

Pattern Download (mobile)
  → expo-file-system downloads to DocumentDirectory
  → react-native-pdf renders from local path
  → Offline access: ✓
```

### Risks Flagged

1. **App Store review** — PDF viewing + user uploads may trigger Apple's "reader app" rule requiring IAP. Mitigation: patterns are user's own files (private vault), not content sold by the app.
2. **expo-router deep links** — iOS requires `Associated Domains` entitlement for universal links. Scaffold this in `app.json` now, not at release.
3. **WatermelonDB migration** — schema changes require explicit `migrations` array; must be treated as seriously as Alembic migrations.
4. **PDF memory on older Android** — `react-native-pdf` is memory-hungry. Cap viewable file size at 25MB; show a warning for large files.

### What's Eliminated vs. Web

- `vite-plugin-pwa` / service workers — replaced by native app installation
- `browser-image-compression` — replaced by `expo-image-manipulator`
- `react-pdf` — replaced by `react-native-pdf`
- CORS configuration on FastAPI — still needed (dev tooling), but not a production concern
- Web manifest / PWA install prompt — replaced by App Store / Play Store

Now writing updated `spec.md` and `tasks.md`:





---

## Summary

**Architecture recommendation: React Native + Expo SDK 51 over a bare React Native setup.**

Justification: Expo's managed build pipeline (EAS Build) eliminates native toolchain complexity without sacrificing capability. The bare workflow is available if a native module requires it.

**Biggest migration impact: offline storage layer.**

Dexie.js/IndexedDB is gone. WatermelonDB on SQLite is the correct replacement — it's relational (handles `parent_counter_id`), lazy-loaded (no memory pressure on older Android), and has first-class React Native support. The sync architecture (idempotency keys, background fetch) is carried forward unchanged from the web plan.

**What stays the same:** FastAPI backend, PostgreSQL, JWT auth, hierarchical counter model, private-only pattern storage, 25MB upload cap, path sanitization. The entire backend is reusable.

**Top risk to flag to the team:** Apple App Store review may scrutinize PDF viewing + upload. The mitigation is clear: these are user's *own* files (private vault), no content sold or distributed — document this explicitly in the App Store submission notes.

### Frontenddev
# Frontend Proposal: React Native for Yarn Loop Clone

## Framework: React Native (Expo SDK 51+)

**Why React Native over Flutter/native:**
- Single codebase for iOS + Android with ~95% code share
- Expo's managed workflow eliminates native build complexity for MVP
- Strong ecosystem for offline-first apps (WatermelonDB, MMKV)
- Reanimated 3 handles the smooth gesture interactions knitters expect (swipe to increment counters, pattern scrolling)

**Why not Flutter:** Dart ecosystem is thinner for pattern/PDF rendering. **Why not native:** No reason to duplicate effort at this stage.

---

## State Management: Zustand + React Query (TanStack Query)

- **Zustand** for local UI state (active counter, current row, UI mode) — minimal boilerplate, plays well with MMKV persistence
- **TanStack Query** for server-sync of patterns and projects — built-in background refetch, stale-while-revalidate
- **MMKV** (via `react-native-mmkv`) for persisting counter state offline — 10x faster than AsyncStorage, synchronous reads for counter increments

---

## Offline Row Counters

Critical feature. Architecture:

```
Counter state → Zustand slice → MMKV persisted store
                                      ↓
                              Background sync queue → API when online
```

Use `@react-native-community/netinfo` to detect connectivity. Queue mutations with TanStack Query's `persistQueryClient` + `createAsyncStoragePersister`.

---

## Pattern Viewing

- **React Native WebView** for rendering HTML/PDF patterns from web imports
- **react-native-pdf** for native PDF rendering (better performance than WebView for large files)
- **Expo FileSystem** for caching downloaded patterns locally
- Custom row-highlighting overlay using Reanimated 2 absolute positioned views

---

## Component Library: Tamagui

Tamagui over NativeWind/StyleSheet because:
- Compile-time styles (faster than StyleSheet at runtime)
- Responsive theming built-in (dark mode for late-night knitting sessions)
- Cross-platform primitives that feel native on both platforms

Alternative: **React Native Paper** if Material Design is acceptable — more opinionated but faster to ship.

---

## Navigation: Expo Router (file-based)

- Type-safe routes, deep linking out of the box
- Tab navigator for: Projects | Patterns | Counter | Settings
- Stack navigator within Projects for drill-down

---

## Build Tooling

- **EAS Build** for CI/CD — cloud builds, OTA updates via EAS Update
- **Maestro** for E2E testing (simpler than Detox for gesture-heavy apps)

---

## Key Tradeoffs to Flag

| Decision | Tradeoff |
|---|---|
| Expo managed | Limits native modules; eject if needed for BLE (smart needle integration?) |
| Tamagui | Steeper initial setup vs faster runtime |
| MMKV over SQLite | No relational queries; fine for counter state, not for complex pattern search |

### Backenddev
# Backend Recommendations: Yarn Loop Clone (React Native)

## Stack: FastAPI + PostgreSQL + Redis + Supabase

### Language & Framework
**FastAPI (Python 3.11+)** — not Django, not Flask. Reasons:
- Native async support handles concurrent websocket connections from mobile clients efficiently
- Auto-generated OpenAPI docs accelerate mobile dev integration
- Pydantic v2 for schema validation matches well with structured knitting pattern data

### Database Strategy

**PostgreSQL (primary)** — knitting patterns are inherently relational:
```
patterns → sections → rows → stitches
users → projects → row_counter_state
```
Use `JSONB` columns for stitch-by-stitch pattern definitions (flexible schema without going full NoSQL).

**Redis (session + sync layer)**:
- Row counter sync buffer: mobile writes optimistically offline, Redis holds the pending delta queue
- TTL-based cache for pattern reads (patterns rarely change, read constantly)

**Supabase** as the managed Postgres host — gives you real-time subscriptions via websockets for free, critical for multi-device sync.

### API Design: REST + WebSocket hybrid

**REST** for CRUD (patterns, projects, user accounts). No GraphQL — overkill for this domain, adds mobile bundle weight.

**WebSocket** for live row counter sync:
```
ws://api/v1/projects/{id}/counter
```
Mobile sends counter deltas, server reconciles conflicts using last-write-wins with timestamp vector.

### Offline-First Architecture

This is the critical mobile concern. Strategy:

1. Mobile stores row counter state in **SQLite via expo-sqlite**
2. On reconnect, client sends a `sync_payload` with local mutations + last sync timestamp
3. Server applies **CRDT-style merge** — counter increments are commutative, safe to merge
4. Server returns authoritative state; client overwrites local

### Rate Limiting & Caching

- **slowapi** (FastAPI middleware) — 100 req/min per authenticated user
- Pattern assets (images, PDFs) served via **Cloudflare R2** with CDN caching, not through the API server
- Counter sync endpoint exempt from rate limits but throttled server-side to 1 write/second per project

### Third-Party Integrations

- **Stripe** for premium pattern purchases — use webhooks, not polling
- **RevenueCat** for in-app purchase abstraction (iOS + Android unified)
- **Firebase Cloud Messaging** for push notifications (row milestone alerts)

### Key Files to Spec

```
api/
  routers/patterns.py      # REST CRUD
  routers/projects.py      # user project state
  routers/sync.py          # WebSocket counter sync
  models/pattern.py        # Pydantic + SQLAlchemy
  services/sync_engine.py  # CRDT merge logic
  services/cache.py        # Redis abstraction
```

**Non-negotiable:** All financial data (pattern prices, purchases) uses `Numeric(10,2)` — never `float`.

### Researcher
I will now analyze the project from a Researcher's perspective, focusing on the proposed shift to React Native for iOS/Android, especially considering the offline capabilities.

My analysis will cover:
1.  **React Native Maturity and Ecosystem**: Stability, community support, and key libraries.
2.  **Adoption Trends and Case Studies**: Real-world examples of success and failure.
3.  **Offline-First Considerations**: Strategies and tools for robust offline functionality.
4.  **Recommendations for Yarn Loop Clone**.

I will use `google_web_search` to gather the necessary evidence.
The transition to a React Native-based mobile application for the Yarn Loop Clone is a strategically sound decision, aligning with current industry trends and leveraging a mature, well-supported framework. This analysis evaluates the proposed shift, focusing on technology maturity, best practices, and specific considerations for offline capabilities.

### React Native: A Mature and Strategic Choice

React Native has evolved significantly, particularly with its "New Architecture" (Fabric, TurboModules) now enabled by default in recent versions (e.g., 0.74). This modernization moves beyond the asynchronous bridge, offering synchronous UI updates and substantial performance gains, especially for complex interactions. The Hermes JavaScript engine further boosts startup times and reduces memory footprint, delivering a near-native user experience.

The ecosystem boasts robust corporate backing from Meta, Shopify, Microsoft, and Amazon, underscoring its enterprise readiness. Developer satisfaction remains high, with studies indicating strong positive sentiment regarding its direction. **Expo** has emerged as the recommended development platform, transforming from a prototyping tool into a comprehensive suite for building, deploying, and managing production-grade React Native applications. Its tooling (EAS, Expo Router) drastically simplifies many pain points associated with native module management and build processes, making cross-platform development more efficient.

### Offline-First Architecture for Yarn Loop Clone

The requirement for offline row counters and pattern viewing necessitates a robust offline-first architecture. This is a well-established pattern in mobile development, and React Native offers several mature solutions:

1.  **Data Storage**:
    *   **For Structured Data (Patterns, Rows)**: `WatermelonDB` is highly recommended. It's built on SQLite but optimized for React Native's reactive paradigm, offering excellent performance for large, complex datasets through lazy loading and observable queries. Alternatively, `react-native-sqlite-storage` provides direct SQLite access for more granular control.
    *   **For Simple Key-Value (Settings, UI State)**: `react-native-mmkv` is an excellent choice. It's significantly faster than `AsyncStorage` (up to 20x) due to its memory-mapped file approach, ideal for frequently accessed, less complex data.

2.  **Synchronization Strategy**: Implement an **Optimistic UI** approach where local changes are applied immediately, enhancing perceived performance, while synchronization with the backend occurs in the background. A dedicated synchronization layer should:
    *   Utilize `[@react-native-community/netinfo]` to detect network availability and trigger syncs.
    *   Maintain an outbound queue for actions performed offline, processing them when connectivity is restored. Libraries like `TanStack Query` or `Redux Persist` can assist in managing this queue and caching.
    *   Incorporate conflict resolution mechanisms (e.g., "last write wins" or user-prompted merges) for scenarios where data is modified both offline and online.

### Potential Challenges and Mitigations

While robust, React Native development can encounter challenges:

*   **Fragmented Package Ecosystem**: Some third-party libraries may be unmaintained. Mitigation: Rigorous vetting of dependencies and prioritizing actively developed, community-backed, or Expo-supported modules.
*   **Native Module Complexity**: While Expo abstracts much of this, highly specific native functionalities (e.g., advanced hardware integrations beyond standard device APIs) might still require custom native module development. Mitigation: Leverage Expo's managed workflow as much as possible; for truly custom needs, ejecting to a bare workflow or using TurboModules should be considered early.
*   **Performance Optimization**: For very intensive animations or data manipulations, fine-tuning might be necessary. `React Native Reanimated` and `React Native Skia` are the go-to libraries for high-performance graphics.

### Recommendation

Adopting React Native for the Yarn Loop Clone is a strong recommendation. Its maturity, performance, and vibrant ecosystem provide a solid foundation for a dedicated mobile experience. To ensure success:

1.  **Prioritize Expo Managed Workflow**: Maximizes development speed and simplifies build/deployment.
2.  **Implement Robust Offline Data Storage**: Choose `WatermelonDB` for complex pattern/row data and `MMKV` for fast key-value storage.
3.  **Design a Clear Synchronization Layer**: Crucial for a seamless offline experience, incorporating optimistic UI, network detection, and conflict resolution.
4.  **Embrace Modern Libraries**: Leverage `React Native Reanimated` for animations and state management solutions like `Zustand` or `TanStack Query` for efficient data handling.

This approach will yield a performant, maintainable, and user-friendly mobile application.

### Devops
# DevOps Perspective: Yarn Loop Clone — React Native Mobile

## Deployment Target

**Backend:** Single VPS (Hetzner CX21, ~$5/month) or Railway.app for zero-ops convenience. This is not a high-traffic app — a small knitting counter tool doesn't need Kubernetes.

- API: Dockerized Node.js/FastAPI container
- Database: PostgreSQL (managed via Railway or self-hosted with daily `pg_dump` to S3)
- No load balancer needed at launch; add Caddy as reverse proxy + TLS

**Mobile:** React Native distributed via:
- iOS: App Store (TestFlight for beta)
- Android: Google Play (internal track for beta)

## CI/CD Pipeline

**GitHub Actions** — straightforward, free tier sufficient:

```
Push → Lint + Type Check → Unit Tests → Build (Expo EAS) → Deploy API → Notify
```

- Use **Expo EAS Build** for managed React Native builds — eliminates Xcode/Android Studio CI complexity
- OTA updates via **Expo Updates** for JS bundle changes (bypasses app store review for non-native changes)
- API deploy: `docker build → push to GHCR → SSH deploy` or Railway auto-deploy on main merge

## Infrastructure-as-Code

**Docker Compose** for the backend — Terraform is overkill here. One `compose.yml` covers API + Postgres + Redis (if needed for sessions).

## Observability

- **Sentry** (free tier): crash reporting for both React Native and backend — single SDK, covers both platforms
- **Uptime Kuma** (self-hosted): API health checks, 1-minute intervals
- **Expo's built-in analytics** or PostHog (self-hosted) for usage patterns
- Structured JSON logging on the backend; no ELK stack needed at this scale

## Offline-First Architecture Impact

The offline row counter requirement changes the data sync story:

- **SQLite via `expo-sqlite`** for local persistence — patterns and counters survive airplane mode
- **Sync endpoint** (`POST /sync`) with last-write-wins or vector clock conflict resolution
- Background sync on app foreground via `AppState` listener

This means the backend is *not* the source of truth during active use — design the API as a sync target, not a real-time dependency. Reduces backend load significantly.

## Scaling Strategy

Don't over-engineer. Scale triggers:
1. **Vertical first:** Upgrade VPS before adding horizontal complexity
2. **CDN for pattern assets** (images, PDFs): Cloudflare R2 free tier handles this
3. Only revisit if DAU exceeds ~10k — at that point, add a read replica

## Cost Estimate (MVP)

| Service | Cost/month |
|---|---|
| VPS (Hetzner CX21) | $5 |
| Managed Postgres (Railway) | $0–$10 |
| Expo EAS (personal) | $0 |
| Sentry (free) | $0 |
| **Total** | **~$5–15** |

**Bottom line:** Keep it boring. Expo EAS removes the worst of mobile CI pain. A single Docker host is plenty. Add complexity only when metrics demand it.

## Debate Round 2: Critiques & Refinements
### Architect
Both files are empty. I'll write the updated `spec.md` and `tasks.md` now, incorporating the challenges from this round.

---

## Round 2 Challenge: Architect

The proposals are directionally correct but contain **three significant conflicts** that need resolution before implementation begins.

### Challenge 1: MMKV vs WatermelonDB — Stop the Split-Brain

FrontendDev proposes **MMKV** for counter state; I proposed **WatermelonDB**. BackendDev proposes **expo-sqlite** directly. This is three teams heading toward three different offline storage layers for the same data — a maintenance disaster.

**Ruling: WatermelonDB exclusively for all structured offline data.**

MMKV is a key-value store. Counter state is relational (`counter → project → sections → rows`). Shoving a relational graph into MMKV means hand-rolling joins in JavaScript. That's what SQLite is for. WatermelonDB gives us the SQLite backend *and* the reactive query layer. MMKV stays only for truly flat settings (user preferences, auth tokens supplement).

### Challenge 2: WebSocket Counter Sync is Premature

BackendDev proposes a `ws://api/v1/projects/{id}/counter` WebSocket for live counter sync. DevOps correctly says this app won't hit 10k DAU at launch. A persistent WebSocket per active project is expensive headroom for a counter that increments ~once per minute.

**Ruling: REST + idempotency keys for counter sync. Re-evaluate WebSocket at 1k DAU.**

The background sync architecture (expo-background-fetch → POST /counters/{id}/sync) already handles the primary use case. WebSocket adds reconnect logic, heartbeats, and stateful server complexity. Defer it.

### Challenge 3: Supabase Introduces a Hard Dependency Risk

BackendDev recommends Supabase for managed Postgres + real-time subscriptions. DevOps recommends Railway or a plain VPS. These are incompatible deployment targets.

**Ruling: Plain PostgreSQL on Railway (or Hetzner) with Alembic migrations. No Supabase.**

Supabase real-time only matters if WebSocket sync is in scope — which it isn't (see Challenge 2). Supabase's free tier also has a pausing policy that would kill a dormant app. Own your Postgres.

### What I'm Endorsing

- **Expo SDK 51 + expo-router**: Agreed across all agents. Lock it in.
- **EAS Build + EAS Update OTA**: DevOps is right — eliminates Xcode CI pain.
- **FastAPI + Numeric types + Alembic**: Backend is solid. Keep it.
- **Sentry for crash reporting**: Agreed. Single SDK covers RN + FastAPI.
- **25MB PDF cap + react-native-pdf**: Agreed. Document in spec.

Now writing the updated files:





---

## Round 2 Challenges Summary

### Three Conflicts Resolved

**1. Storage layer conflict (MMKV vs WatermelonDB vs expo-sqlite):**
WatermelonDB wins for all relational data. MMKV is restricted to flat settings only. `expo-sqlite` direct is eliminated — WatermelonDB sits on top of it correctly.

**2. WebSocket for counter sync is premature:**
Deferred. REST + idempotency keys handles the use case. The counter increments ~once per minute; a persistent socket per project is over-engineering. Revisit at 1k DAU.

**3. Supabase dependency removed:**
Plain PostgreSQL on Railway/Hetzner with Alembic migrations. Supabase's real-time value proposition is zero without the WebSocket layer. Its free-tier pause policy is a liability for a dormant MVP.

### Endorsements Confirmed
- Expo SDK 51 + expo-router + EAS Build: locked in across all agent proposals
- FastAPI + Numeric types + Alembic: solid, unchanged
- Sentry (single org, both RN and Python): agreed

`spec.md` and `tasks.md` written with full implementation detail: function signatures, Pydantic/WatermelonDB schemas, explicit file paths, and dependency ordering per the CLAUDE.md task protocol.

### Frontenddev
## Frontend Challenge: Round 2

### Challenge 1: MMKV is Wrong for Counter State — Use WatermelonDB Consistently

The FrontendDev proposal splits storage across two systems: MMKV for counters, WatermelonDB for patterns/projects. This creates a sync nightmare.

Counters are **not** simple key-value data. A knitting project has hierarchical counters (`main_rows → sleeve_rows → decrease_rows`), each with its own `parent_counter_id`, target value, reset triggers, and sync history. MMKV stores blobs — you cannot query "all counters for project X that are past their target" without deserializing everything. WatermelonDB handles this natively with observable queries.

**Ruling:** Single storage layer. WatermelonDB for all persistent domain data. MMKV is appropriate only for non-domain state (theme preference, last-opened project ID, auth token caching alongside `expo-secure-store`).

---

### Challenge 2: Tamagui is a Trap for MVP

Tamagui's compile-time optimization is real, but its setup cost is not acceptable for a first-ship timeline. It requires a Babel plugin, a custom Metro transformer, and theme configuration that interacts poorly with Expo's managed workflow until you've burned 2–3 days debugging why your tokens don't resolve on Android.

**Ruling:** Use **NativeWind v4 + @gluestack-ui/themed**. NativeWind v4 uses a static CSS extraction approach that's faster to configure and the Tailwind mental model transfers directly from any web experience on the team. Gluestack provides accessible, tested native primitives. This combination ships faster and is easier to hand off.

Revisit Tamagui post-MVP if bundle performance becomes measurable.

---

### Challenge 3: Drop the WebSocket for Counter Sync

The BackendDev proposes `ws://api/v1/projects/{id}/counter` for live counter sync. This is overengineered for the actual problem: a single user incrementing rows on one device at a time.

WebSockets on mobile are expensive — they require persistent TCP connections that iOS and Android will aggressively kill in the background. You then need reconnection logic, heartbeat pings, and a fallback REST path anyway.

**The simpler, more resilient design:**

```
Increment tapped
  → WatermelonDB write (immediate, <1ms)
  → Enqueue mutation: { idempotency_key, project_id, delta, timestamp }
  → On foreground / netinfo "connected" event:
      POST /api/v1/projects/{id}/sync  ← REST, not WebSocket
      Body: { mutations: [...pending] }
      Response: { server_state, conflicts: [] }
```

This is crash-safe, network-agnostic, and testable without a WebSocket mock. The idempotency key (already in the Architect's plan) makes this safe to retry without double-counts. WebSockets are justified only if multi-device real-time sync becomes a requirement — it is not in this spec.

---

### What I'm Not Challenging

- **Expo SDK 51 + EAS Build** — correct call, no argument
- **expo-router** — file-based navigation is the right default
- **TanStack Query for server-sync layer** — agreed
- **react-native-pdf for pattern viewing** — correct, WebView is slower for multi-page PDFs

The Architect's backend-unchanged conclusion is sound. The only frontend-layer corrections needed are storage consolidation, component library pragmatism, and eliminating the WebSocket complexity that mobile networks will punish in production.

### Backenddev
## Backend Challenge: Round 2

### Drop WebSockets. Counters Don't Need Them.

My Round 1 proposal included a WebSocket endpoint for counter sync. I'm retracting it.

A knitting counter is not a collaborative real-time document. Users knit alone. The "live sync" requirement is *multi-device*, not *multi-user-concurrent*. A persistent WebSocket connection on mobile is expensive: it fights iOS/Android background restrictions, drains battery, and adds connection lifecycle complexity (reconnect on foreground, handle network handoff from WiFi to LTE).

**Replace with:** `POST /sync` called on app foreground + network restore. Simple, stateless, mobile-friendly.

```
AppState → foreground
  → netinfo: online?
  → flush local delta queue
  → POST /api/v1/sync { mutations: [...], last_synced_at: ISO8601 }
  → server returns authoritative state
  → overwrite local
```

---

### Drop Redis at MVP. Postgres Can Handle This.

I proposed Redis for a "sync buffer." The DevOps agent correctly flagged over-engineering. At MVP scale, a `sync_queue` table in Postgres handles pending mutations — it's durable (survives server restart), queryable (debugging is trivial), and eliminates an infrastructure dependency.

```sql
CREATE TABLE sync_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    project_id UUID NOT NULL,
    idempotency_key UUID NOT NULL UNIQUE,
    delta INTEGER NOT NULL,
    client_ts TIMESTAMPTZ NOT NULL,
    processed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

Add Redis *only when* queue depth under load becomes a Postgres bottleneck. That's a good problem to have later.

---

### Challenge FrontendDev: MMKV vs WatermelonDB Is a False Choice

FrontendDev chose MMKV for counter state; Architect chose WatermelonDB. Both are right for different things — but the proposal needs to be explicit:

| Data | Storage | Why |
|---|---|---|
| Counter increment deltas (sync queue) | **MMKV** | Synchronous write, <1ms, safe for tap handler |
| Counter hierarchy + project structure | **WatermelonDB** | Relational, `parent_counter_id`, lazy-load |
| Auth tokens | **expo-secure-store** | OS keychain |

Using MMKV as the *only* store fails when a project has 20 nested section counters and the user queries "show all counters for project X." That's a query, not a key lookup.

---

### Hard Blocker: RevenueCat Replaces Stripe for In-App Purchases

I listed both in Round 1. This is wrong. Apple **requires** IAP for digital content sold within an iOS app — using Stripe directly violates App Store guidelines and risks rejection/removal. 

**RevenueCat only** for mobile IAP. Stripe is still valid for web-originated purchases or physical goods (e.g., a future "buy yarn" feature), but that's out of scope.

---

### What Stands

- FastAPI + PostgreSQL + Alembic: unchanged, correct
- `Numeric(10,2)` for all pricing: non-negotiable
- Path sanitization + user-scoped file storage: carry forward
- `slowapi` rate limiting: 100 req/min per user is right

The backend is simple by design. Resist the urge to add infrastructure that the scale doesn't justify yet.

### Researcher
## Researcher Challenge & Recommendations: Yarn Loop Clone Mobile

The proposed shift to React Native is a solid foundation, leveraging a mature framework with strong community and corporate backing. The "New Architecture" (Fabric, TurboModules) and Hermes engine in modern React Native versions (e.g., 0.74+) significantly enhance performance and address previous concerns regarding native integration. Expo, particularly with EAS Build and Expo Router, further streamlines development, making it an excellent choice for rapid, high-quality mobile app delivery.

### Offline Data Storage: Hybrid Approach Recommended

There's a divergence in the offline storage proposals: Architect suggests `WatermelonDB` for all structured data, while FrontendDev proposes `MMKV` for counter state. BackendDev mentions `expo-sqlite`. For optimal performance and maintainability, a hybrid approach combining the strengths of both is recommended:

*   **`WatermelonDB` for Complex Relational Data (Patterns, Projects)**: This aligns with Architect's proposal. `WatermelonDB` (built on SQLite) is optimized for large, reactive datasets in React Native. Its lazy-loading and observable queries are crucial for efficiently managing complex knitting patterns (`patterns → sections → rows → stitches`) and project data without memory bottlenecks, especially on older devices. Companies like **Delivery Much** and **Oura** have successfully utilized similar SQLite-based solutions for complex offline data.
*   **`MMKV` for High-Frequency, Simple State (Current Counter Value)**: This aligns with FrontendDev's proposal. `MMKV` is a lightning-fast key-value store (up to 20x faster than AsyncStorage), ideal for synchronously reading and writing the *current* row counter value. Its speed ensures immediate UI updates for the core interaction. Projects requiring high-performance state persistence, such as **Shopify's FlashList**, leverage similar memory-mapped solutions.

The BackendDev's mention of `expo-sqlite` provides the underlying technology, but `WatermelonDB` offers a higher-level, more developer-friendly API for managing relational data effectively.

### Component Library: Prioritize Maintainability and Adoption

FrontendDev proposes `Tamagui`, while Architect suggests `NativeWind + @gluestack-ui`. While `Tamagui` offers advanced compile-time optimizations and a cohesive design system, it has a steeper learning curve and a smaller adoption base compared to Tailwind CSS (`NativeWind`).

*   **Recommendation: `NativeWind` paired with `NativeBase` (or `@gluestack-ui`)**: Leveraging `NativeWind` allows the team to utilize `Tailwind CSS`, a widely adopted styling methodology across web and increasingly mobile projects. This familiarity significantly reduces the learning curve and broadens the pool of potential contributors. Pairing `NativeWind` with a mature, accessible component library like `NativeBase` (or its successor `@gluestack-ui` for newer projects) provides pre-built, robust UI elements, balancing customizability with rapid development. This combination has been successfully adopted by various startups and agencies for its blend of utility-first styling and robust component offerings.

### Backend Sync Strategy: Simplify Conflict Resolution

BackendDev proposes a "CRDT-style merge" for counter synchronization. While CRDTs are powerful for complex collaborative editing (e.g., text documents), they introduce significant complexity. For a simple, commutative operation like "increment counter by X," a simpler approach is more pragmatic and less error-prone:

*   **Recommendation: Idempotent Delta Sync with Server-Side Reconciliation**: As Architect implicitly suggested, sending a `delta` (e.g., `+1`) along with an `idempotency_key` (UUID) to the backend's `/sync` endpoint is sufficient. The FastAPI backend can then:
    1.  Check the `idempotency_key` in a dedicated table to prevent duplicate application.
    2.  Apply the delta to the authoritative counter value.
    3.  Resolve any potential offline-online conflicts using "last-write-wins" based on a client-provided timestamp, or by simply applying all distinct, idempotent deltas.

This strategy is simpler to implement and debug than full CRDTs, providing robust eventual consistency for counter increments. Many financial transaction systems and simple counting applications use similar idempotent request patterns to ensure data integrity.

### Observability: Sentry is Key

DevOps' proposal for `Sentry` for crash reporting is strongly endorsed. `Sentry` is widely adopted across the mobile and web ecosystem (e.g., **Uber, Microsoft, Airbnb**) for its comprehensive error tracking, performance monitoring, and cross-platform support. It's an indispensable tool for identifying and resolving issues quickly in production.

### Devops
## DevOps Challenge: Round 2

### Challenge 1: BackendDev's Stack Is Over-Engineered for This Domain

The BackendDev proposed: Supabase + Redis + WebSockets + CRDT merge logic. That's four moving parts for a **knitting counter app**.

**Direct challenge:** Drop the WebSocket endpoint for counter sync entirely.

A knitter tapping [+] offline does not need a live WebSocket session — they need reliable eventual consistency when they return online. WebSockets introduce:
- Connection state management on mobile (app background/foreground cycles kill sockets)
- Additional infra (stateful connection handling doesn't work well behind standard reverse proxies)
- Operational complexity for zero marginal UX benefit

The Architect's idempotency key pattern over plain REST is the correct answer here. The BackendDev's own description (`sync_payload` + last sync timestamp on reconnect) *is* REST, not WebSocket. Use REST. Ditch the socket.

**Redis is also unnecessary at MVP.** PostgreSQL's `FOR UPDATE SKIP LOCKED` handles the counter write queue. Add Redis only when you have measured evidence of contention.

### Challenge 2: Storage Layer Conflict Must Be Resolved

FrontendDev chose **MMKV** for counter state. Architect chose **WatermelonDB**. These are not interchangeable — pick one and commit.

My position: **WatermelonDB wins**, but only if the team is willing to own its migration discipline. Here's why MMKV fails for this use case:

- `parent_counter_id` (hierarchical counters) requires relational queries — MMKV is a flat key-value store
- Pattern metadata (row annotations, section markers) is relational data, not blobs
- MMKV has no schema migration story; WatermelonDB does

**The DevOps implication:** WatermelonDB schema migrations must be treated identically to Alembic migrations — reviewed, versioned, and tested before EAS builds. Add a CI step that runs the WatermelonDB migration array against a fresh DB on every PR. This is not optional.

### Challenge 3: EAS Build Pipeline Needs Secrets Management Defined Now

Both the Architect and FrontendDev waved past this. EAS Build requires:

- App Store Connect API keys
- Google Play service account JSON
- `EXPO_TOKEN` for CI
- Backend API URLs per environment (dev/staging/prod)

These must be in **EAS Secrets** (not GitHub Actions secrets) because EAS Build runs on Expo's cloud, not your runner. Define the environment matrix now:

```
eas.json
├── development  → local API, debug bundle
├── preview      → staging API, TestFlight internal / Play internal track
└── production   → prod API, App Store / Play Store
```

Not having this costs a full sprint when it's retrofitted.

### What I'm Endorsing

- Architect's FastAPI backend (unchanged from web) — correct, reuse it
- My Round 1 infra sizing — single VPS + Docker Compose + EAS Build is still right
- Sentry for both RN crash reporting and FastAPI exceptions — one dashboard, two SDKs

### Bottom Line

The complexity ceiling for this project's infra is: **one Postgres instance, one FastAPI container, EAS cloud builds, Sentry.** Everything above that line needs a measured justification, not architectural enthusiasm.

## Final Synthesis & Architecture Recommendation
# Final Recommendation: Yarn Loop Clone - Mobile Migration

## 1. Executive Summary

This project refines the Yarn Loop Clone by pivoting the frontend from a web application to a native mobile app for iOS and Android, built with **React Native and Expo**. The primary driver is to deliver a superior, dedicated mobile experience with robust offline capabilities, specifically for row counting and pattern viewing. The existing **FastAPI backend remains largely unchanged**, proving the soundness of the initial architecture. Key disagreements between agents have been resolved, prioritizing a pragmatic, scalable, and maintainable stack for the Minimum Viable Product (MVP).

## 2. Recommended Tech Stack

| Layer | Technology | Reasoning |
| :--- | :--- | :--- |
| **Mobile App** | React Native (Expo SDK 51+) | **Unanimous decision.** A mature, single-codebase solution for iOS & Android. Expo's managed workflow (EAS Build) drastically reduces native toolchain complexity. |
| **Navigation** | Expo Router | **Unanimous decision.** Provides file-based, type-safe navigation and deep-linking out of the box. |
| **UI Components**| NativeWind v4 + @gluestack-ui | **Resolved conflict.** This combination offers the developer ergonomics of Tailwind CSS with a set of accessible, performant native components, prioritizing MVP speed over the steeper setup of alternatives like Tamagui. |
| **Offline Storage**| **WatermelonDB** (Relational) & **MMKV** (Key-Value) | **Resolved conflict (Hybrid Approach).** WatermelonDB (on SQLite) will manage all structured, relational data (projects, pattern metadata, counter hierarchy). MMKV provides fast, synchronous writes for immediate UI feedback on high-frequency actions like counter increments. `expo-secure-store` will be used exclusively for auth tokens. |
| **Data Sync** | TanStack Query | Manages server state, caching, and background data synchronization. |
| **Backend** | FastAPI (Python) + PostgreSQL + Alembic | **Unanimous decision.** The existing backend is performant and reusable. The proposal to add Redis and WebSockets was **rejected** as over-engineering for the MVP. |
| **Deployment** | Docker Compose on a VPS (e.g., Railway, Hetzner) | **Resolved conflict.** Simple, cost-effective, and sufficient for the projected scale. Supabase was **rejected** to avoid vendor lock-in and its unsuitable free-tier policies. |
| **CI/CD** | GitHub Actions + Expo EAS Build & Update | **Unanimous decision.** EAS Build solves the mobile CI/CD problem. EAS Update enables over-the-air (OTA) updates for non-native code changes, bypassing app store review. |
| **Observability**| Sentry | **Unanimous decision.** A single tool for crash reporting and performance monitoring across both the React Native and FastAPI codebases. |
| **IAP**| RevenueCat | **Critical Correction.** Direct use of Stripe for digital goods violates App Store guidelines. RevenueCat is mandatory for abstracting and managing in-app purchases on iOS and Android. |

## 3. Architecture Overview

The architecture prioritizes a robust offline-first experience. The mobile client is the primary source of truth during offline use, syncing with the backend when connectivity is available.

```
┌───────────────────────────────────────────────┐
│        React Native App (Expo SDK 51)         │
│                                               │
│ ┌────────────┐   ┌─────────────┐  ┌─────────┐ │
│ │  Counter   │   │  Projects   │  │ Patterns│ │
│ │ (Offline)  │   │   (CRUD)    │  │ (Viewer)│ │
│ └─────┬──────┘   └──────┬──────┘  └────┬────┘ │
│       │                 │              │      │
│ ┌─────▼──────────┐ ┌────▼──────────────▼────┐ │
│ │ MMKV (sync K/V)│ │ WatermelonDB (SQLite)  │ │
│ │ Counter writes │ │ Relational data store  │ │
│ └────────────────┘ └──────────┬─────────────┘ │
│                                │ Background    │
└────────────────────────────────┼───────────────┘
                                 │ REST Sync
                                 │ (Idempotent POST)
┌────────────────────────────────▼───────────────┐
│              FastAPI Backend (Docker)         │
│       (Projects, Users, Patterns, Sync)       │
│                                               │
│    Alembic Migrations | SQLAlchemy ORM        │
└────────────────────────────────┬───────────────┘
                                 │
                    ┌────────────▼───────────┐
                    │     PostgreSQL DB      │
                    └────────────────────────┘
```

**Counter Sync Flow:**
1.  User taps to increment a counter.
2.  The new value is written **synchronously to MMKV** for immediate UI feedback (<1ms).
3.  An asynchronous task updates the relational record in **WatermelonDB**.
4.  A mutation (e.g., `{ idempotency_key, delta: 1 }`) is added to a sync queue.
5.  On app foreground or network reconnection, the queue is flushed via a `POST /api/v1/sync` request to the FastAPI backend.

## 4. Key Risks & Mitigations

1.  **App Store Rejection:** Apple may flag the app as a "reader app" due to PDF functionality, requiring IAP.
    *   **Mitigation:** Clearly state in the review notes that all patterns are user-owned, private files. The app does not distribute or sell content.
2.  **Offline Schema Migrations:** WatermelonDB schema changes can break the app if not handled correctly.
    *   **Mitigation:** Treat WatermelonDB migrations with the same rigor as backend Alembic migrations. Add a CI step to validate migrations on every pull request.
3.  **Build Secrets Management:** EAS builds run on Expo's cloud and require secure access to API keys and environment variables.
    *   **Mitigation:** Define and populate `eas.json` secrets for `development`, `preview`, and `production` environments from the start.

## 5. Implementation Phases

*   **Phase 1: Foundation & Setup (1-2 Sprints)**
    *   Initialize React Native project using Expo.
    *   Set up EAS Build pipeline with `eas.json` secrets.
    *   Integrate Sentry for crash reporting.
    *   Establish file-based navigation with Expo Router for main tabs (Projects, Patterns, Settings).
    *   Implement basic user authentication against the existing backend.

*   **Phase 2: Core Offline MVP (2-3 Sprints)**
    *   Model schemas for Projects and Counters in WatermelonDB.
    *   Implement full CRUD functionality for Projects.
    *   Build the core counter UI, using the MMKV/WatermelonDB hybrid strategy for offline increments.
    *   Implement the background REST sync service using TanStack Query to flush pending mutations to the backend.

*   **Phase 3: Pattern Viewing & Polish (2 Sprints)**
    *   Integrate `react-native-pdf` for viewing pattern files.
    *   Implement file downloading and caching using `expo-file-system` for offline pattern access.
    *   Add UI polish, including haptic feedback (`expo-haptics`) for counter interactions and a dark mode theme.

## 6. Open Questions

*   Is real-time, multi-device sync a firm future requirement? If so, WebSockets may need to be re-evaluated post-MVP (at >1k DAU).
*   What are the specific data points and relationships required for the `Pattern` and `Counter` schemas? This needs detailed definition before Phase 2 begins.
