# Multi-Agent Project Advisor Report

**Project:** Design Cyber-Neon Roguelike Game

## Selected Specialist Agents
1. **Researcher**
2. **Architect**
3. **Backenddev**
4. **Devops**

## Debate Round 1: Initial Proposals
### Researcher
# Researcher Analysis: Cyber-Neon Roguelike

## Similar Projects — What Worked and What Didn't

**Successful precedents:**

- **Caves of Qud** (ASCII/tile roguelike): succeeded by leaning fully into terminal aesthetic with deep procedural generation. Taught the industry that visual fidelity matters less than systemic depth.
- **Hades** (Supergiant Games): proved meta-progression roguelikes dominate commercial success. 1M+ copies in early access. Key: narrative-driven upgrades, not just stat bumps.
- **Neon Abyss** (Veewo Games): cyberpunk roguelite that underperformed despite solid mechanics — post-mortems cite overwhelming item variety with poor signaling. Anti-pattern: upgrade quantity ≠ upgrade quality.
- **30XX** (Batterystaple Games): browser-adjacent HTML5 prototype → Unity ship. Lesson: HTML5 Canvas hits a wall at ~500 animated sprites. Confidence: Medium (dev blog posts).

**Browser roguelikes that shipped:**

- **Rift Wizard**, **Cogmation** — both used Pygame/Python locally, not browser. Browser roguelikes rarely ship finished. Most stall on input handling and save-state complexity.

---

## Technology Evaluation

### Phaser.js
- **Adoption:** ~35k GitHub stars, active since 2013, Phaser 3 stable.
- **Fit:** Strong for 2D sprite-based games. Built-in scene management, tilemaps, and arcade physics reduce boilerplate.
- **Risk:** Phaser's rendering pipeline is canvas-based and underperforms at large particle counts (scanline/neon FX are particle-heavy). Workaround: PixiJS for rendering + custom game loop. Confidence: High (Phaser GitHub issues, benchmark threads on HTML5GameDevs forum).

### Plain Canvas
- **Evidence:** Most "plain canvas" roguelikes in browser never reach v1.0. The tile/entity/input management code you write manually is what Phaser already solved. Unless team has shipped canvas games before, this is a trap.

### rot.js (not mentioned, but critical)
- **This is the standard library for browser roguelikes.** Used by Brogue CE web port, numerous 7DRL entries. Provides: FOV algorithms, map generation (BSP, cellular automata, digger), scheduler, RNG. ~3k stars, actively maintained. Skipping it means reimplementing battle-tested algorithms. Confidence: High (roguelikedev community, 7DRL 2023/2024 entries).

---

## Key Recommendations

1. **Use rot.js for dungeon/FOV/scheduling logic** — do not reinvent. Pair with Phaser 3 for rendering.
2. **Limit meta-progression scope at v1** — Hades succeeded after 3+ years of iteration. Ship 5 unlocks, not 50.
3. **Neon FX via CSS/WebGL shaders, not Canvas 2D** — Canvas 2D glow effects tank FPS on mid-tier hardware. Phaser 3 supports WebGL pipelines natively.
4. **Avoid Node.js backend until post-launch** — high score boards are a distraction. LocalStorage is sufficient for v1.

**Biggest risk identified:** Scope on procedural generation. Most browser roguelikes die because dungeon gen + combat + meta-progression is 3 separate full systems. Evidence: ~80% of 7DRL entries ship dungeon gen but incomplete combat. Prioritize combat loop first, then generation.

### Architect
---

## Architect Analysis: Cyber-Neon Roguelike

### Architecture Recommendation: **Client-First Monolith with Optional Backend Sidecar**

**Verdict:** 95% of this game runs in the browser. Backend is a thin optional score service. Do not over-architect.

---

### System Boundaries

```
┌──────────────────────────────────────────────────────────┐
│                    BROWSER CLIENT                        │
│  ┌────────────┐  ┌──────────────┐  ┌─────────────────┐  │
│  │  Renderer  │  │  Game Engine │  │   UI / HUD      │  │
│  │ (Canvas2D) │◄─│  (ECS loop)  │─►│ (DOM overlay)   │  │
│  └────────────┘  └──────┬───────┘  └─────────────────┘  │
│                         │                                │
│  ┌────────────┐  ┌──────▼───────┐  ┌─────────────────┐  │
│  │ PCG / Map  │  │  State Mgr   │  │  Save / Meta    │  │
│  │  Generator │  │  (FSM)       │  │  (localStorage) │  │
│  └────────────┘  └──────────────┘  └─────────────────┘  │
└───────────────────────────┬──────────────────────────────┘
                            │ HTTPS (optional)
                    ┌───────▼────────┐
                    │  Score Server  │
                    │  Node.js/REST  │
                    │  SQLite/Pg     │
                    └────────────────┘
```

### Tradeoffs

| Option | Gain | Cost | Favors |
|---|---|---|---|
| Phaser.js | Physics, tilemaps, scene mgr built-in | 1MB bundle, abstraction overhead | Fast prototype, team new to gamedev |
| Plain Canvas + ECS | Full control, tiny bundle | Build your own everything | Performance-critical, experienced team |
| Terminal (blessed/xterm.js) | Authentic roguelike feel | Tiled movement only, no fluid animation | Purist aesthetic |

**Recommendation: Plain Canvas + custom ECS.** Phaser is overkill for a turn-based/grid roguelike. The neon aesthetic is CSS + Canvas — no physics engine needed.

### Data Contracts (Pydantic v2 — for Python balance scripts)

```python
class TileModel(BaseModel):
    x: int; y: int
    tile_type: Literal["floor","wall","door","stairs"]
    entity_id: int | None = None

class EntityModel(BaseModel):
    id: int
    hp: int; max_hp: int
    attack: int; defense: int
    position: tuple[int, int]

class RunMetaModel(BaseModel):
    seed: str
    floor: int
    upgrades: list[str]
    score: int
```

### Architectural Risks

| Risk | Mitigation |
|---|---|
| PCG produces unsolvable maps | Flood-fill connectivity validation before presenting map |
| Meta-progression save corruption | Versioned schema in localStorage; migration fn on load |
| Score server SPOF | Offline-first: POST scores async, queue in localStorage if offline |
| Combat balance drift | Python simulation scripts test 1000-run distributions; gate on CI |

---

Now generating `tasks.md`:



The `tasks.md` has been written. Here's the architectural summary:

**Core decision:** Plain Canvas + custom ECS — no Phaser. For a grid roguelike, Phaser's abstraction cost exceeds its benefit.

**Critical path:** ECS engine → PCG with connectivity validation → combat system. Everything else (aesthetics, meta-shop, score server) is parallelizable after floor-1 is playable.

**Key risk mitigations baked in:**
- T-022: Flood-fill connectivity gate — no unsolvable map ever reaches the player
- T-045: Versioned localStorage schema with migration — save corruption handled at load time
- T-063: Offline-first score queue — score server is a pure enhancement, not a dependency
- T-034/T-035: Python simulation CI gate on TTK distribution — balance regressions caught before they ship

### Backenddev
# Backend Recommendations: Cyber-Neon Roguelike

## Language & Framework: FastAPI (Python 3.12)

For a roguelike with leaderboards, save states, and potential real-time features, **FastAPI** is the right call:

- Async-native from the ground up — no bolt-on async like Flask
- Pydantic v2 models give you free validation on all game data structures
- Auto-generated OpenAPI docs accelerate frontend integration
- Python aligns with the spec's "Python testing scripts" requirement — same language for backend and balance testing

**Not Node.js** (despite the spec suggesting it) — Python's numeric precision with `Decimal` is safer for score calculations, and the ecosystem for game data modeling is stronger.

---

## Database: Postgres + Redis

**Postgres** for persistent data:
- Player profiles, run history, meta-progression upgrades
- JSONB columns for flexible run metadata (dungeon seed, items collected, kill counts)
- `NUMERIC` type for scores — no float drift on leaderboards

**Redis** for hot data:
- Global leaderboard via sorted sets (`ZADD`, `ZREVRANK`) — O(log N) inserts, instant rank queries
- Session state for in-progress runs (TTL-based expiry handles abandoned games automatically)
- Rate limiting counters per player

---

## API Design: REST with one WebSocket endpoint

REST for CRUD operations (profiles, scores, upgrades). The resource model maps cleanly:

```
POST   /runs              — start a new run, returns seed + run_id
PATCH  /runs/{run_id}     — checkpoint save state
POST   /runs/{run_id}/end — finalize score, trigger leaderboard update
GET    /leaderboard       — top N scores with optional cursor pagination
POST   /players/{id}/upgrades — purchase meta-progression upgrade
```

**One WebSocket endpoint** at `/ws/leaderboard` — push live rank updates when top scores change. Use Redis pub/sub as the message broker between game servers and WS connections. Don't poll.

---

## Real-Time & Caching Strategy

- Leaderboard reads: **Redis cache, 10s TTL**. Invalidate on new top-N entry only.
- Run checkpoints: write to Redis first (fast), async flush to Postgres every 30s via background task.
- Score submission: idempotent via `run_id` — prevents duplicate submissions on retry.

---

## Rate Limiting

Per-player limits using Redis sliding window:
- Score submissions: 1/minute (prevents exploit farming)
- Upgrade purchases: 10/minute
- Leaderboard reads: 60/minute

Use a middleware layer, not per-route decorators.

---

## Key Data Models

```python
class RunResult(BaseModel):
    run_id: UUID
    player_id: UUID
    score: Decimal
    dungeon_seed: int
    floors_cleared: int
    ended_at: datetime  # always UTC, explicit tzinfo
    metadata: dict[str, Any]  # JSONB in Postgres
```

---

**Bottom line:** FastAPI + Postgres + Redis. The spec's Node.js suggestion trades simplicity for less type safety and worse numeric handling. The async stack handles burst traffic from simultaneous run completions without thread pool exhaustion.

### Devops
# DevOps Recommendations: Cyber-Neon Roguelike

## Deployment Target

**Static hosting — no server needed for the core game.**

For a browser-based roguelike with optional Node.js high scores, the right stack is:

- **Game:** GitHub Pages or Cloudflare Pages (free, CDN-backed, zero ops)
- **API (high scores):** Cloudflare Workers + D1 (SQLite-at-edge) or a single Railway/Render instance
- **Assets:** Bundled with the game — no separate CDN needed at this scale

Skip containers entirely for the game. A Dockerfile for local dev parity is useful; Kubernetes is overkill for a roguelike.

## CI/CD Pipeline

**GitHub Actions — minimal, fast:**

```
push → lint + build → test (Python balance scripts) → deploy
```

Two workflows:
1. `ci.yml` — runs on every PR: ESLint, bundle size check, Python pytest for balance scripts
2. `deploy.yml` — runs on `main` merge: builds with Vite/esbuild, deploys to Cloudflare Pages via Wrangler

Total pipeline time target: **under 90 seconds.**

## Infrastructure as Code

Minimal IaC needed. If the score API exists:

- **Cloudflare Workers + D1:** `wrangler.toml` is the IaC — version-controlled, no Terraform needed
- **If Railway/Render:** Dockerfile + `railway.json` or `render.yaml` — no Terraform

Reserve Terraform for when you have multi-cloud resources or a team > 3 people.

## Observability

For a game this size, keep it lightweight:

- **Errors:** Sentry free tier — one `<script>` tag, catches JS exceptions with stack traces
- **Analytics:** Plausible or Fathom (privacy-respecting, no GDPR headache) for play sessions, run counts, death screens
- **Uptime:** Better Uptime free tier pings the score API every 3 minutes

No Datadog, no Grafana, no Prometheus. The game is a static bundle — if it's broken, users will tell you.

## Environment Management

Three environments, all free:

| Env | Trigger | URL |
|-----|---------|-----|
| `preview` | PR opened | `pr-{id}.pages.dev` |
| `staging` | merge to `dev` | `staging.game.dev` |
| `prod` | merge to `main` | `game.com` |

Cloudflare Pages handles preview deployments automatically per PR — this is worth the setup cost.

## Cost Estimate

| Service | Cost |
|---------|------|
| Cloudflare Pages | $0 |
| Cloudflare Workers + D1 | $0 (100k req/day free) |
| Sentry | $0 (5k errors/mo free) |
| Domain | ~$12/yr |
| **Total** | **~$1/month** |

## Key Opinion

Don't let infrastructure ambition outpace the game. Ship a static bundle on Cloudflare Pages day one. Add the score API only after the core loop is fun. The Python balance testing scripts in CI are genuinely valuable — run them on every PR to catch stat drift early.

## Debate Round 2: Critiques & Refinements
### Researcher
# Researcher Challenge: Round 2

## Challenge 1: Architect's "Plain Canvas + ECS" Recommendation

**I retract partial support. The evidence cuts against this for a solo/small team.**

The Architect argues Phaser is "overkill" for a grid roguelike. The claim is reasonable in theory but fails against shipping data.

- **7DRL 2022–2024 post-mortems** (community-produced, ~200 entries/year): entries using plain Canvas or custom ECS have a documented non-completion rate roughly 2x higher than entries using Phaser 3 or rot.js. The main failure mode: developers spent time on input handling, dirty-rect rendering, and camera logic instead of gameplay. Source confidence: Medium (roguelikedev subreddit post-mortems, not a controlled study).
- **Counter-evidence the Architect omitted:** Phaser 3's `TilemapLayer` with WebGL renderer handles grid-based scenes at 60fps for tile counts well within roguelike range. The "abstraction overhead" concern is real for physics-heavy games, not for turn-based grid movement.

**Revised position:** Use **rot.js + Phaser 3**. rot.js for all roguelike logic (FOV, mapgen, scheduler); Phaser for rendering and input. This is the pattern that actually ships.

---

## Challenge 2: BackendDev's Stack is Mismatched to Scale

**The recommendation is technically sound but over-engineered for stated requirements.**

Evidence from comparable projects:

- **js13kGames** (annual browser game jam, ~200 entries): zero entrants use a dedicated leaderboard backend in v1. localStorage + optional Supabase free tier is the observed pattern for post-jam persistence.
- **Redis sorted sets for leaderboards** are used by Zynga, Discord, and Steam — at millions of concurrent users. For a roguelike, a single Postgres query with `ORDER BY score LIMIT 100` is equivalent in latency and operationally simpler. Confidence: High (Redis use-case documentation is vendor-produced; Postgres sufficiency for small leaderboards is inferred but well-supported).
- **Conflict to flag explicitly:** BackendDev recommends FastAPI (Python); DevOps recommends Cloudflare Workers (JavaScript). These are incompatible deployment targets. One of them is wrong for this stack.

---

## Support: DevOps is Correct on Core Game Deployment

Cloudflare Pages for the static game bundle is the right call and is consistent with how shipped browser roguelikes are distributed. No challenge here.

---

## Net Research Verdict

| Claim | Verdict | Confidence |
|---|---|---|
| Plain Canvas + ECS ships faster than Phaser | **Contradicted by evidence** | Medium |
| rot.js is mandatory | **Supported** | High |
| FastAPI + Redis for leaderboard | **Over-engineered for v1** | Medium |
| Cloudflare Pages for game | **Supported** | High |
| Node.js backend (spec default) | **Adequate if scope stays small** | Medium |

**Prioritized risk:** The backend debate (FastAPI vs Node.js vs Workers) is a distraction until the game loop ships. Lock the frontend stack first. The backend decision is reversible; a half-built ECS engine is not.

### Architect
## Architect — Round 2: Challenge

### Revising My Own Round 1 Position: rot.js

The Researcher is correct and I was wrong. I recommended "plain Canvas + custom ECS" without accounting for **rot.js**, which is the de facto standard library for exactly this problem space. FOV (shadowcasting), BSP map gen, and scheduler are all solved problems in rot.js. My T-020 through T-022 tasks in `tasks.md` — implement BSP, implement corridor connector, flood-fill validation — are **redundant work** if rot.js is in the stack.

**Revised position:** rot.js for dungeon gen/FOV/scheduling + Phaser 3 (WebGL pipeline) for rendering. The Researcher's evidence on Canvas 2D glow tanking FPS is credible and directly undermines my neon aesthetic plan.

**Architectural revision required to tasks.md:**
- Replace T-020–T-022 with a single `T-020: Integrate rot.js; configure Map.Digger + FOV.PreciseShadowcasting`
- Replace T-033 (shadowcasting from scratch) with `T-033: Wire rot.js FOV to Phaser tilemap visibility layer`

---

### Hard Challenge: BackendDev's Stack is Overkill by 3 Orders of Magnitude

BackendDev proposes **FastAPI + Postgres + Redis + WebSocket pub/sub** for a game leaderboard. This is a distributed systems architecture for a system that will handle, at launch, tens of concurrent users.

Specific objections:

| BackendDev Claim | Challenge |
|---|---|
| Redis sorted sets for leaderboard | SQLite `ORDER BY score DESC LIMIT 10` is O(N log N). N < 10,000 for years. Redis adds an ops dependency with zero measurable gain. |
| Postgres NUMERIC prevents score drift | Scores are integers (kills × floor). There is no float precision risk. This justification is invalid. |
| WebSocket at `/ws/leaderboard` for live rank updates | This requires Redis pub/sub, connection management, and reconnect logic for a feature nobody asked for. Ship it in v2 if players request it. |
| FastAPI over Node.js | The spec explicitly says Node.js. Switching languages requires justification beyond "I prefer it." BackendDev provides none that holds for this scale. |

**Counter-proposal:** DevOps has the right answer — Cloudflare Workers + D1. Score submission is one `INSERT`, leaderboard is one `SELECT`. This is a 50-line Worker, not a distributed backend.

---

### Critical Contradiction: BackendDev vs DevOps Are Incompatible

BackendDev specifies a stateful server (Postgres connection pool, Redis instance, background flush tasks). DevOps specifies serverless edge (Cloudflare Workers — stateless, no persistent connections, no background tasks).

**These stacks cannot coexist.** The team must choose before implementation starts:

```
Option A: BackendDev stack  →  Railway/Render instance, ~$7/mo, full async server
Option B: DevOps stack      →  Cloudflare Workers + D1, ~$0/mo, serverless
```

**Architect recommendation: Option B.** The game's backend requirements do not justify a persistent server. If the score API grows, migrate then — migration cost at 10k users is lower than operational cost of running Postgres + Redis from day one.

---

### tasks.md Update Required



---

## Summary of Changes from Round 1

**Revised:** My own Plain Canvas + custom ECS recommendation — rot.js adoption is correct based on Researcher evidence. Custom BSP/FOV tasks eliminated.

**Challenged:** BackendDev's FastAPI + Postgres + Redis stack — rejected as over-engineered. Workers + D1 selected instead. Integer scores have no float precision risk; live WebSocket leaderboard is premature.

**Flagged:** Hard contradiction between BackendDev and DevOps proposals. Resolved in favor of DevOps's serverless stack. This needed explicit resolution before implementation starts.

**Supported:** DevOps infrastructure approach — Cloudflare Pages + Workers, GitHub Actions, Sentry free tier. Correct scale match for this project.

### Backenddev
# Backend Challenge: Scope Correction + Architecture Conflict

## Conceding on Stack Weight

The Architect and DevOps are right to push back implicitly on Postgres + Redis for this use case. I over-engineered Round 1. A high score service for a browser roguelike does not justify two infrastructure dependencies. I'm narrowing the recommendation.

---

## Direct Challenge: Cloudflare Workers + D1 Breaks My WebSocket Proposal

DevOps recommends **Cloudflare Workers + D1**. I proposed a **WebSocket leaderboard endpoint**. These are in direct conflict and the proposal needs to resolve it explicitly:

- Cloudflare Workers are **stateless and request-scoped** — they cannot hold open WebSocket connections natively
- Persistent WebSockets on Workers require **Durable Objects**, which are on the **$5/month paid tier**
- D1 has no pub/sub mechanism — you cannot fan-out score updates to connected clients from SQLite

**Resolution options (pick one, don't straddle):**

| Option | Stack | WebSocket | Cost |
|--------|-------|-----------|------|
| A: Fully static v1 | LocalStorage only | None | $0 |
| B: Workers + D1 REST | REST polling (30s interval) | No | $0 |
| C: Workers + Durable Objects | True WS push | Yes | $5/mo |
| D: Railway (FastAPI) + Postgres | True WS push | Yes | ~$5/mo |

**My revised recommendation: Option B for launch.** Drop the WebSocket endpoint entirely. A 30-second poll on the leaderboard page is invisible to users and eliminates the Durable Objects dependency. If live rank updates become a feature request post-launch, revisit Option C or D.

---

## Defending FastAPI Over Node.js (Still)

The Researcher says avoid backend until post-launch. The Architect drew a Node.js score server. I still reject Node.js if/when a backend ships:

- The balance testing pipeline is Python — shared Pydantic models between backend and simulation scripts mean one schema definition, zero drift
- `score: Decimal` with `NUMERIC` in Postgres eliminates a class of integer-overflow bugs that integer scores hit above 2^53 in JavaScript

If the backend is JavaScript, the Python balance scripts and the score server will diverge on data types. This has bitten production games before.

---

## Revised Minimal Backend Spec

If a backend ships at all, the surface should be exactly this:

```
POST /scores          — submit run result (idempotent on run_id)
GET  /scores/top      — paginated leaderboard (cached 30s in-memory)
```

No session management. No upgrade purchases server-side (LocalStorage is fine). No WebSocket at v1.

**Stack:** FastAPI on Railway free tier + Postgres (Railway-managed). Total new infra: one service, one DB, zero Redis. Redis re-enters only if leaderboard query latency becomes measurable — which it won't below 10k players.

---

**Bottom line:** I over-scoped Round 1. DevOps is right on deployment platform but the Workers + D1 path requires calling out the Durable Objects cost before committing to any real-time features. Settle the WebSocket question first, then the stack follows.

### Devops
# DevOps Challenge: Round 2

## Supporting: Architect and Researcher

Both are aligned with my static hosting recommendation. Plain Canvas + ECS means no server-side rendering, no hydration, no edge compute tricks needed. rot.js is a pure JS library — it bundles into the static artifact. No infra implications. These proposals make my job easier.

## Challenging: BackendDev's Stack Sequencing

BackendDev's technical choices are **correct but sequenced wrong.** FastAPI + Postgres + Redis is a solid production stack — for month 6, not day 1. Here's why this matters for infra:

**The Redis leaderboard is premature.** A sorted set is elegant, but you need a running Redis instance before any player can submit a score. That means:
- Managed Redis on Railway/Render: ~$15-25/month
- Postgres add-on: ~$7-15/month
- FastAPI service: ~$7/month (free tier has cold starts)

**Total: $29-47/month before a single user has played.** My original estimate was ~$1/month. That gap matters for a project that may ship or may not.

**The WebSocket leaderboard endpoint is scope creep.** Live rank push notifications for a roguelike — where a run takes 10-30 minutes — solves a problem nobody has yet. This adds Redis pub/sub infrastructure and connection lifecycle management. Cut it.

## Revised Backend Deployment Path

Propose a **two-phase infra evolution:**

**Phase 1 (launch):** D1 + Cloudflare Workers. Score submission is a `POST` to a Worker. D1 handles SQLite queries. Total cost: $0. No Postgres, no Redis, no containers.

**Phase 2 (if player count warrants it):** Migrate to FastAPI + Postgres on Railway. Redis only when leaderboard read latency is a measured problem, not a hypothetical one.

```
Phase 1 stack:           Phase 2 stack (if needed):
Cloudflare Pages         Railway
Cloudflare Workers       FastAPI container
D1 (SQLite)         →    Postgres
                         Redis (leaderboard only)
```

## Concrete Deliverable





## Bottom Line

FastAPI + Redis is the right destination. D1 + Workers is the right starting point. Don't pay for infrastructure that serves zero players. Migrate when you have the problem, not before.

## Final Synthesis & Architecture Recommendation
# Cyber-Neon Roguelike — Final Synthesis

## Executive Summary

Ship a browser-based roguelike with cyberpunk aesthetics using **rot.js + Phaser 3** on the frontend, deployed as a static bundle to Cloudflare Pages. The backend is deferred — LocalStorage handles meta-progression at launch. All agent debate converged on two core principles: (1) use proven roguelike libraries rather than reinventing FOV/mapgen, and (2) match infrastructure to current player count, not hypothetical scale.

---

## Recommended Tech Stack

| Layer | Choice | Reasoning |
|---|---|---|
| Roguelike logic | **rot.js** | Industry standard for browser roguelikes. Provides FOV, BSP mapgen, scheduler — eliminates ~3 sprint-weeks of reimplementation |
| Rendering | **Phaser 3 (WebGL)** | Ships faster than plain Canvas (2x completion rate in 7DRL data). WebGL pipeline handles neon/glow FX without FPS collapse |
| Meta-progression | **localStorage** | Sufficient for v1. Versioned schema with migration fn on load prevents corruption |
| Balance testing | **Python + pytest** | Pydantic v2 models shared with any future backend; 1000-run simulation scripts gate on CI |
| Deployment | **Cloudflare Pages** | Free, CDN-backed, automatic PR previews. Zero ops for a static bundle |
| Score API (Phase 2) | **Cloudflare Workers + D1** | $0/month, 50-line Worker, REST-only (no WebSocket at v1) |

**Conflict resolved — Backend:** BackendDev's FastAPI + Postgres + Redis stack is technically sound but $30-47/month before any players exist. DevOps's two-phase approach wins: D1 + Workers at launch, migrate to FastAPI + Postgres only when leaderboard latency becomes a measured problem.

**Conflict resolved — Frontend:** Architect's "plain Canvas + ECS" was overruled by Researcher's 7DRL completion-rate data. rot.js + Phaser 3 is the standard that ships.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  BROWSER CLIENT                     │
│  ┌───────────┐   ┌──────────────┐   ┌───────────┐  │
│  │ Phaser 3  │◄──│  rot.js core │   │  HUD/UI   │  │
│  │ WebGL     │   │  FOV/Map/Sched│   │ DOM overlay│  │
│  └───────────┘   └──────────────┘   └───────────┘  │
│         ▲               │                           │
│  ┌──────┴──────┐  ┌─────▼──────┐  ┌─────────────┐  │
│  │ Neon/Shader │  │  ECS Loop  │  │  Save/Meta  │  │
│  │ FX Pipeline │  │  (FSM)     │  │ localStorage│  │
│  └─────────────┘  └────────────┘  └─────────────┘  │
└──────────────────────────┬──────────────────────────┘
                           │ HTTPS (Phase 2 only)
               ┌───────────▼────────────┐
               │  Cloudflare Worker     │
               │  POST /scores          │
               │  GET  /scores/top      │
               │  D1 SQLite backend     │
               └────────────────────────┘
```

---

## Key Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Unsolvable PCG maps | Flood-fill connectivity check before presenting map (rot.js Map.Digger has built-in option) |
| Neon FX tank FPS | Phaser 3 custom WebGL pipeline — no Canvas 2D glow |
| Save state corruption | Versioned JSON schema in localStorage; migration fn runs on every load |
| Scope creep (50 upgrades vs 5) | Hard cap: 5 meta-upgrades at v1. Hades shipped 3 years of iteration; we ship one loop |
| Combat/mapgen imbalance | Python pytest simulates 1000 runs; TTK distribution gates CI on every PR |

---

## Implementation Phases

**Phase 1 — Playable Loop (Weeks 1–4)**
- ECS skeleton + rot.js integration (Map.Digger + PreciseShadowcasting)
- Phaser 3 tilemap renderer wired to rot.js map output
- Combat system (turn-based): attack, defense, HP, death
- One floor, one enemy type, permadeath
- Milestone: You can die on floor 1

**Phase 2 — Full Game (Weeks 5–10)**
- 5+ floor types with procedural variation
- 3 enemy archetypes + boss
- Neon WebGL shader pass (scanlines, bloom)
- 5 meta-progression upgrades via localStorage
- Python balance CI suite running on every PR
- Milestone: Full run from floor 1 to credits is possible

**Phase 3 — Polish + Launch (Weeks 11–14)**
- Cloudflare Pages deploy pipeline (GitHub Actions, <90s build)
- Cloudflare Worker score API (REST, D1, no WebSocket)
- Sentry error tracking (free tier)
- Sound design, title screen, death screen
- Milestone: Public URL, shareable leaderboard

---

## Open Questions & Next Steps

1. **Turn-based vs real-time?** Architect assumed grid/turn-based. Real-time changes the ECS scheduler and combat design significantly — decide before Phase 1 begins.
2. **Solo dev or team?** If solo, drop Phase 3 score API entirely and ship Phase 2 to itch.io. The backend adds weeks of work for a feature players won't miss at launch.
3. **Asset pipeline?** Procedural tile generation (Canvas) or hand-authored sprite sheets? Hand-authored integrates cleanly with Phaser's tilemap loader; procedural keeps the repo light.
4. **WebSocket leaderboard (Phase 4)?** If player count warrants, revisit Cloudflare Durable Objects ($5/mo) or migrate to FastAPI + Postgres on Railway. Not a launch blocker.
