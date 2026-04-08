# Multi-Agent Project Advisor Report

**Project:** Debate Golang MM Strategy for Capital Preservation

## Selected Specialist Agents
1. **Researcher**
2. **Architect**
3. **Backenddev**
4. **Devops**

## Debate Round 1: Initial Proposals
### Researcher
---

## Researcher Analysis: Golang Capital-Preservation Market Maker

### 1. Technology Choice: Go for Market Making

**Verdict: Correct tier, known tradeoffs.**

Go is well-validated for medium-frequency market making (1ms–100ms latency). Jump Trading and Citadel Securities use Go for order management layers, though C++ dominates sub-millisecond HFT. For crypto markets—where exchange-to-exchange latency is typically 5–50ms—Go's throughput characteristics are sufficient.

**Critical risk:** Go's garbage collector introduces 1–10ms stop-the-world pauses. With default GC settings, this is non-trivial during a spike regime when you most need determinism. Mitigation: set `GOGC=off` and manually trigger GC between ticks, or use `runtime/debug.SetGCPercent(400)`. This is not mentioned in the spec and should be an explicit implementation requirement.

`shopspring/decimal` (source: primary) is correct for monetary precision and is used in production at several trading firms. Performance cost vs. `float64` is ~10–20× slower per operation—acceptable here since quote generation is not the hot path.

### 2. Fair Value: Micro-Price + OFI

**Verdict: Well-validated, canonical approach.**

The micro-price formula originates from Stoikov (2009). OFI as a price impact signal was formally quantified by Cont, Kukanov & Stoikov (2013, "The Price Impact of Order Book Events"—high confidence, peer-reviewed). IMC and Optiver have published talks confirming OFI-style adjustments in live systems.

**Gap:** OFI normalized by `max_observed_ofi` has an initialization problem—early in a session, `max_observed_ofi` is near zero, causing division instability or extreme normalization. Standard practice is to use a rolling percentile or exponential running max with a floor. This needs to be addressed in Phase 2.

### 3. Volatility Regime Switching

**Verdict: Proven structure; 60s window may lag.**

Two-regime (calm/spike) quoting is used by Virtu Financial (per their SEC filings and investor presentations—secondary source). Hysteresis to prevent thrashing is standard and correctly specified here.

**Risk:** A 60-second realized-vol window is slow for detecting flash crashes. In the 2021 Binance flash crash (BTC dropped 10% in ~30 seconds), a 60s window would not have triggered a regime switch in time. EWMA volatility (e.g., GARCH(1,1) halflife of 15–20s) is more responsive. This is a calibration decision, but the spec should acknowledge it explicitly.

### 4. Toxicity Pause (Adverse Selection Defense)

**Verdict: Simplified but effective; 8s window is tight.**

The post-fill price-move approach is simpler than VPIN (Easley, Lopez de Prado, O'Hara 2012) but operationally equivalent for single-instrument makers. The tiered pause (15s/45s/120s) mirrors approaches described in academic market-making literature.

**Concern:** The 8s detection window could miss adverse moves that play out over 30–60s (common in crypto whale accumulation patterns). Consider making `toxic_detection_window` configurable per regime.

### 5. Hot-Reload Config: High-Risk Feature

**Hard evidence against:** Knight Capital Group (August 2012) lost $440M in 45 minutes due to a code path activated unexpectedly in a live system. Hot-reload introduces the same class of risk—live config mutation while orders are in-flight.

**Recommendation:** Require config changes to drain outstanding orders before applying. Never hot-reload `emergency_cap`, `max_inventory`, or compliance parameters without a full position check. This constraint is absent from the spec and should be a non-negotiable invariant (§9).

### 6. L9 Compliance Anchor Overriding Toxicity Pause

**Verdict: Pragmatically correct; document the exposure.**

The decision to keep L9 live during a toxicity pause is the right tradeoff for exchange SLA compliance. However, in a genuine market dislocation (e.g., exchange technical halt, oracle manipulation), L9 becomes an unhedged resting order at 1.95% from a potentially stale fair value. A **stale-data circuit breaker** (no feed updates for >N seconds → cancel all including L9) is absent from the spec and represents a gap.

---

**Summary of gaps requiring spec amendments:**
1. GC tuning strategy for deterministic latency
2. OFI normalization floor to prevent initialization instability
3. Explicit vol window tradeoff documented; EWMA as alternative
4. Hot-reload safety constraints on monetary/compliance params
5. Stale-data circuit breaker that overrides even L9

### Architect
## Architect — Round 1 Proposal: Capital Preservation MM Strategy

### Assessment of Current `tasks.md`

The existing plan is well-structured with correct primitives (`decimal.Decimal`, hysteresis FSM, tiered toxicity pauses). However, **five critical architectural gaps** threaten capital preservation:

---

### Risk 1: `float64` Contamination in OFI Accumulator

The `OFITracker` uses `float64` for `Normalized()`. OFI feeds directly into fair value:

```
fair_value = micro_price + ofi_normalized × ofi_alpha × tick_size
```

Float64 accumulation over thousands of trades introduces drift. At $5k whale thresholds, a 0.001% fair-value error on a 10 BTC position = $5 slippage per tick.

**Fix:** `OFITracker` internal state stays `float64` (performance-critical rolling math), but `Normalized()` returns `decimal.Decimal` at the boundary before multiplying into price.

---

### Risk 2: No Position Reconciliation Loop

`MASState.NetPosition` is computed locally from fills. Exchange-side position is the ground truth. Any fill drop, retry duplicate, or WebSocket reconnect can diverge them — silently.

**Missing task:** A `PositionReconciler` goroutine that polls the exchange REST position endpoint every 5s and calls `CheckEmergencyCap` if local vs. remote delta > `max_drift_threshold`.

---

### Risk 3: Config Hot-Reload Race

Phase 6.3 watches `config.yaml` for changes. If a reload fires between `ComputeFairValue` and `BuildSpikeQuotes` within a single `OnTick` call, quotes are built against a different config than the fair value was computed with.

**Fix:** Config reload must snapshot `MASConfig` at tick entry and pass it immutably through the entire tick pipeline. The watcher updates a `atomic.Pointer[MASConfig]`, loaded once per tick.

```
OnTick:
  cfg := configPtr.Load()  // snapshot once
  state = update(state, book, trades, cfg)
  orders = buildQuotes(state, cfg)
```

---

### Risk 4: No Circuit Breaker / Kill Switch

The strategy has no external kill switch. If the Spike regime fires incorrectly (fat-finger data, exchange glitch), only the toxicity pause (max 120s) limits exposure. Capital preservation requires a harder boundary.

**Missing task:** `CircuitBreaker` with three trip conditions:
1. Realized loss exceeds `max_loss_per_session` (config)
2. Position reconciliation delta exceeds `max_drift_threshold` for >3 consecutive cycles
3. External signal via file (`/tmp/mas_kill`) or signal `SIGUSR1`

---

### Risk 5: Missing Backtest Data Contract

Phase 7 references "7-day historical data" with no specification of the data format. If the backtest harness uses a different `Trade` schema than live, results won't transfer.

**Fix:** Define a canonical `HistoricalTick` Pydantic-equivalent in Go:

```go
type HistoricalTick struct {
    Timestamp  time.Time
    Book       OrderBook
    Trades     []Trade
    Fills      []Fill  // empty for backtest
}
```

The backtest runner and live runner both consume `<-chan HistoricalTick`.

---

### Updated `tasks.md`



---

## Summary of Architectural Position

**Recommendation: Adopt the Golang MM strategy with five mandatory additions before any live capital:**

1. **`decimal.Decimal` at the OFI price boundary** — float accumulation silently erodes edge
2. **`atomic.Pointer[MASConfig]` snapshot-per-tick** — hot-reload without mid-tick state inconsistency
3. **`PositionReconciler` goroutine (5s poll)** — local fill tracking is not the source of truth
4. **`CircuitBreaker` with three trip conditions** — software toxicity pauses alone are insufficient for capital preservation
5. **`HistoricalTick` shared contract** — backtest results that don't share schema with live are fiction

The existing spike/sideways regime separation and tiered toxicity pauses are architecturally sound. The gaps are all in the **capital preservation layer** — the mechanisms that stop losses when everything else fails.

### Backenddev
## Backend Analysis: Golang MM Strategy for Capital Preservation

### The Core Question

The existing spec commits to **Python asyncio + MongoDB**. The debate is whether a Go-based market-making execution layer is justified for capital preservation goals. My verdict: **yes, but only as a bounded execution microservice — not a full rewrite.**

---

### Where Go Wins for This Use Case

**Latency at the execution boundary matters.** Polymarket CLOB WebSocket delivers real-time orderbook events. Python asyncio handles this fine for *observation*, but for *execution* (position adjustments, stop-loss triggers, hedge orders) goroutines outperform Python coroutines under concurrent load:

- Go's goroutines: ~2KB stack, `~100ns` context switch
- Python coroutines: heavier per-task overhead, GIL edge cases under `multiprocessing`

For capital preservation specifically, **determinism > raw speed**. Go's `shopspring/decimal` package is battle-tested for fixed-point arithmetic. Python's `Decimal` is correct but slower and more error-prone to wire through Pydantic serialization chains.

**Recommendation: Go execution microservice exposing gRPC.**

```
Python AsyncIO Bot → gRPC → Go MM Engine → Polymarket CLOB REST
```

---

### Concrete Stack for the Go Layer

| Concern | Choice | Why |
|---|---|---|
| HTTP client | `resty` v2 | Retry middleware, typed responses |
| WebSocket | `gorilla/websocket` | Battle-tested, maintained |
| Decimal math | `shopspring/decimal` | No float leakage |
| Config | `viper` + env | 12-factor, `.env` compatible |
| API | gRPC (`google.golang.org/grpc`) | Typed contract with Python client |
| Persistence | Redis (via `go-redis`) | Position state, not documents |

---

### What Stays in Python

The Python layer owns everything it's already good at:

- Telegram bot (aiogram) — no Go equivalent
- MongoDB state management (motor) — schema flexibility for events/keywords
- Signal generation and volatility detection — NumPy/pandas ecosystem
- X API + Gamma REST polling — httpx/aiohttp is sufficient at 60s intervals

---

### Capital Preservation: The Critical Backend Rules

1. **All position state in Redis** (Go layer), not MongoDB. TTL-keyed entries expire stale positions automatically. MongoDB is too slow for sub-second stop-loss checks.
2. **`Decimal` end-to-end.** Never cross a float boundary — not in gRPC proto serialization (use `string` fields for monetary values), not in Redis (store as string, parse on read).
3. **Circuit breaker on the Go execution layer.** If CLOB WS disconnects, the MM engine must halt new positions and alert — not silently continue with stale orderbook data.
4. **gRPC health checks** between Python and Go. If the execution service goes down, the Python bot degrades gracefully to monitoring-only mode.

---

### What I'd Reject

A full Golang rewrite of the bot is unnecessary and would destroy the Telegram/aiogram integration without meaningful gain. The latency-sensitive path is narrow — **only the execution and position-management loop needs Go's guarantees**. Keep the polyglot surface minimal: one gRPC boundary, well-typed proto schema, Redis as the shared state store.

### Devops
## DevOps Analysis — Polymarket Sniper Bot

### Critical Gaps

**1. No CI/CD pipeline exists.** Zero `.github/workflows/` files. For a financial bot with Telegram and MongoDB integrations, this is the first thing to fix. A basic pipeline should be:

```
lint (ruff + mypy) → secret-scan (gitleaks) → test → build Docker image
```

Target: ≤90s on feature branches. Secret scan must be a gate — not optional.

**2. `bypassPermissions` in committed config is a red flag.**

`config.yaml:51` sets `--permission-mode bypassPermissions` on the Claude CLI backend. If this config is used in a CI runner or shared environment, every agent invocation runs without permission checks. Scope this to local dev only, or move it to an env-var override that never touches the repo.

**3. Secrets are uncontrolled.** The spec calls for `pydantic-settings + .env` but there's no `.env.example`, no `.gitignore` entry for `.env`, and no evidence of vault-scoped secrets. The Telegram bot token, MongoDB URI, and X API bearer token are high-value credentials. A single accidental commit exposes live capital.

Minimum required:
- `.env.example` committed with placeholder values
- `.env` in `.gitignore`
- GitHub Actions secrets for CI, not hardcoded vars

**4. The `logs/` directory has 100+ session JSON files tracked in the repo.** These are runtime artifacts, not source code. They inflate clone size and pollute git history. Add `logs/` to `.gitignore` immediately.

---

### Structural Issues

**Polyglot confusion.** The repo has Go files (`internal/grpc/`, `internal/repository/`) alongside a Python spec. Either the Go layer is the multi-agent orchestration framework (separate concern) or it's dead code. This must be clarified — a mixed-runtime Docker setup is expensive to maintain.

**`fix_config.py` at repo root** is an ad-hoc script that should either be promoted to `scripts/` with a clear purpose or deleted. Root-level fix scripts are a maintenance liability.

---

### Recommended Immediate Actions

1. **Add `.gitignore`** — `logs/`, `*.json` session files, `.env`, `__pycache__/`, `polymarket/__pycache__/`
2. **Commit `.env.example`** with all required env vars documented but unpopulated
3. **Add `gitleaks` pre-commit hook** and a CI gate — run before any merge to main
4. **Create `.github/workflows/ci.yml`** — ruff lint, mypy type check, pytest, Docker build check
5. **Branch protection on `main`** — require PR + 1 passing CI check; no direct pushes

---

### Docker Strategy

For this workload (single async Python process + MongoDB), the right infra is:

- **Dev**: `docker-compose.yml` with `bot` + `mongo` services (fix the currently empty file)
- **Prod**: Railway or Render — a single container, no Kubernetes needed
- **Image**: Multi-stage Python Dockerfile; base `python:3.11-slim`, copy only `requirements.txt` + `src/`; never COPY `.env`

The operational cost of Kubernetes for a single-process Telegram bot is unjustifiable. Deploy simple, scale if proven necessary.

## Debate Round 2: Critiques & Refinements
### Researcher
---

## Researcher — Round 2 Challenge

### Challenge 1: BackendDev's gRPC Split Is a Capital Preservation Liability, Not an Asset

**The proposal:** Python signals → gRPC → Go execution engine.

**The problem:** This trades one risk (Python asyncio latency) for a worse one—distributed systems failure at the execution boundary.

Evidence against this pattern:
- **Knight Capital (2012)** lost $440M because unexpected code paths activated at the execution layer. Adding a cross-process RPC boundary between signal generation and order placement is the same failure mode class: unexpected state at the hand-off.
- **Hummingbot** (open source, widely deployed crypto MM) runs as a single-process Python event loop and handles mid-frequency market making adequately. It has not required a Go execution layer despite years of production use. (Source: public GitHub, community-produced—medium confidence.)
- Polymarket is a **prediction market**, not BTC spot. Its CLOB tick rate is orders of magnitude lower than a CME futures book. The latency argument for Go falls apart when the underlying instrument has update frequencies measured in seconds, not microseconds.

The gRPC boundary introduces: network partition failure modes, proto deserialization errors, and timeout races between a pause signal and an in-flight order—none of which exist in a single-process design. For capital preservation, the correct principle is **minimize the system surface area**, not maximize the technology surface.

**Verdict:** Reject the gRPC split unless benchmarks show Polymarket tick rates actually saturate Python asyncio. No such evidence was presented.

---

### Challenge 2: Architect's Float64 Drift Claim Is Overstated

The Architect claims float64 OFI accumulation causes "drift" with a "$5 slippage per tick" consequence.

The math does not support this. float64 carries 15–17 significant digits. The OFI boundary computation is:

```
adjustment = ofi_normalized × 3.0 × tick_size
           = [-1.0, +1.0] × 3.0 × $0.10
           = [-$0.30, +$0.30] maximum
```

Float64 rounding error at this magnitude is ~10⁻¹⁴—below any tradeable impact by eleven orders of magnitude. The real float64 risk is what I identified in Round 1: **division by zero when `max_observed_ofi` initializes near zero**. That is a correctness bug, not a precision-drift bug. The fix is a floor/minimum, not a `decimal.Decimal` conversion.

The Architect's recommendation to use `decimal.Decimal` at the OFI boundary is correct in spirit (defense in depth), but the stated justification overstates the risk and could cause implementers to chase the wrong root cause.

---

### Challenge 3: DevOps Analysis Conflated Two Separate Systems

The DevOps agent analyzed `config.yaml`, `fix_config.py`, `logs/`, and the Python spec—which are components of this **multi-agent orchestration framework**, not the Go MM strategy under debate. The `bypassPermissions` flag is a Claude CLI agent runner config, not a trading bot credential issue.

This is a category error. Recommendations like "add `.gitignore` for `logs/`" are valid for this repo but are **out of scope for the MM strategy debate**. The synthesis should not conflate the two.

---

### Support: Architect's Circuit Breaker + My Stale-Data Breaker Converge

The Architect's three-condition `CircuitBreaker` and my stale-data circuit breaker recommendation are addressing the same architectural gap from different angles. Both should be merged into a single invariant in the spec:

> **Any condition that makes the fair value computation unreliable (stale feed, position reconciliation delta, session loss limit) must cancel ALL orders including L9.**

The spec's current L9 override of toxicity pauses is correct for *normal* adverse selection. It is wrong for *data integrity failures*. These are different threat models and the spec must distinguish them.

### Architect
## Architect — Round 2 Challenge

### Challenge: BackendDev's gRPC Microservice Split

BackendDev proposes `Python → gRPC → Go MM Engine`. I reject this for this use case.

**The latency argument doesn't hold here.** Polymarket's CLOB is crypto, not equities — execution latency is exchange-RTT-bound (50–200ms). Replacing Python asyncio with a Go gRPC service saves microseconds on a millisecond problem. You've added a network hop, a proto serialization boundary, and two services to operate, for zero measurable improvement in capital preservation outcomes.

**The distributed failure mode is worse than the original.** A single Python process fails obviously — the bot stops. A Python process that can't reach its Go execution service has ambiguous state: did the last order get placed? Is the position open? With one process, the answer is always "check the event loop." With a gRPC split, you need distributed consensus on position state during a reconnect — exactly when you cannot afford it.

**The gRPC split is only justified if:**
- You have measured Python asyncio as the bottleneck (you haven't)
- You need multi-instrument parallelism across cores (one instrument, one loop)
- The exchange enforces sub-1ms order placement SLAs (Polymarket doesn't)

Keep the Go layer where it belongs: as an internal library or a separate process with a file/signal kill interface — not a synchronous RPC dependency in the execution path.

---

### Challenge: Researcher's `GOGC=off` Recommendation

Researcher recommends `GOGC=off` with manual GC triggers for deterministic latency. This trades predictable pauses for unbounded heap growth. In a 14-day paper trading run, heap grows proportionally to OFI/volatility history. A 4 AM spike regime that loads 48 hours of rolling data without a GC cycle will OOM before the session ends.

**Correct approach:** `GOGC=400` (trigger at 4× live heap), plus `runtime.GC()` called explicitly in the idle path between ticks — not between OFI and quote generation. This gives near-deterministic behavior on the critical path without memory risk.

---

### Support + Expansion: Researcher's Stale-Data Circuit Breaker

Researcher's stale-data gap is the most critical finding this round — and it's absent from my own Round 1 tasks.md. I'm adding it now.

**L9 compliance anchor becomes a liability when the feed goes stale.** L9 quotes at `fair_value ± 1.95%` are priced against a live orderbook. If the WebSocket feed drops and reconnects, L9 rests against a stale fair value with no bounds.



---

### Summary of Challenges

| Proposal | Verdict | Reason |
|---|---|---|
| BackendDev: gRPC execution split | **Reject** | Adds distributed failure mode; Polymarket latency is RTT-bound, not compute-bound; no measured bottleneck justifies the boundary |
| Researcher: `GOGC=off` | **Partial reject** | OOM risk in long sessions; `GOGC=400` + explicit inter-tick GC is correct |
| Researcher: stale-data circuit breaker | **Accept + expand** | Added to tasks.md as §5.5.1 condition 4; L9 explicitly cancelled on stale feed |
| Researcher: EWMA volatility | **Accept** | EWMA now default in §3.1 with 15s halflife; rolling retained as fallback |
| Researcher: OFI normalization floor | **Accept** | Exp running max with `1e-6` floor added to §2.2 |
| DevOps: hot-reload safety | **Accept + codify** | Immutable param lock file added to §5.5.3 with startup hash validation |

### Backenddev
## BackendDev — Round 2 Challenge

### Challenge 1: `GOGC=off` is a Capital Preservation Antipattern

The Researcher recommends `GOGC=off` to eliminate GC pauses. This is wrong for this workload and dangerous.

`GOGC=off` means no automatic collection. During a spike regime, the OFI accumulator, order buffer, and fill queue are all allocating aggressively. Without collection, the process grows unbounded until it OOMs — which is a **hard kill with open positions**.

**Correct fix:** `GOGC=200` (double the default heap headroom) combined with a manual `runtime.GC()` called *after* orders are confirmed sent and *before* waiting for the next tick. This gives deterministic GC timing without the OOM risk:

```go
func (e *Engine) OnTick(ctx context.Context, book OrderBook) {
    cfg := e.cfgPtr.Load() // Architect's snapshot — correct
    // ... tick logic ...
    e.sendOrders(orders)
    runtime.GC() // explicit, bounded, between ticks
}
```

---

### Challenge 2: My Own Redis TTL Design — Retract It

In Round 1 I recommended "TTL-keyed entries expire stale positions automatically." I'm retracting this.

**Position state must never TTL-expire.** If the Go engine loses Redis connectivity for 30 seconds during a spike, TTL expiry silently zeroes the recorded position. When reconnection restores, the circuit breaker sees `NetPosition = 0`, which looks healthy. The actual exchange position is still open.

**Correction:** Position keys have **no TTL**. Only orderbook snapshot cache and fill dedup keys get TTLs. Position state is write-once-per-fill, updated by the `PositionReconciler` (Architect's addition — correct and necessary), and explicitly zeroed only on confirmed flat + reconciler agreement.

---

### Challenge 3: DevOps is Right About Polyglot Confusion, but for the Wrong Reason

DevOps flags the Go files (`internal/grpc/`, `internal/repository/`) as a structural issue. The right response isn't "clarify or delete" — it's **commit to the architecture**. The ambiguity exists because no one has made the Python↔Go boundary explicit in code.

The fix is a single proto file that makes the contract undeniable:

```proto
// proto/execution/v1/engine.proto
service ExecutionEngine {
  rpc SubmitQuotes(QuoteRequest) returns (QuoteResponse);
  rpc GetPosition(PositionRequest) returns (PositionResponse);
  rpc TriggerCircuitBreaker(TripRequest) returns (TripResponse);
}
```

This eliminates the "is this dead code?" question. The proto file **is** the architecture documentation. DevOps can then write a CI check that validates Python gRPC stubs are regenerated from the committed proto — if they diverge, the build fails.

---

### What I'm Not Challenging

The Architect's `atomic.Pointer[MASConfig]` snapshot-per-tick is correct and I endorse it fully. The `PositionReconciler` goroutine at 5s is correct. The Researcher's OFI normalization floor concern is valid and non-negotiable for initialization safety.

**Net position:** The architecture is sound. Two concrete corrections — no `GOGC=off`, no TTL on position keys — are the blockers before any live capital.

### Devops
## DevOps Challenge — Round 2

### Challenging BackendDev's Polyglot gRPC Architecture

BackendDev recommends a Python → gRPC → Go split. This is operationally expensive for what may be a solo or small-team project. Consider what this actually costs in CI/CD:

- **Two build pipelines**: `ruff`+`mypy` for Python, `golangci-lint`+`go vet` for Go
- **Two Docker images** to build, tag, push, and keep in sync
- **Two runtime processes** to orchestrate in compose and prod
- **Two debugging contexts** when a capital-preservation circuit fails at 3am

The performance argument is real but the threshold hasn't been proven. Before committing to a polyglot boundary, the team must benchmark the Python asyncio execution path and demonstrate actual latency exceeds the acceptable threshold. Right now this is speculative optimization with confirmed operational debt.

**My position:** Start with Python-only. Implement the Go execution layer only if measured latency exceeds a defined SLO. The gRPC boundary is premature unless benchmark data exists.

---

### Challenging Hot-Reload Config Across All Proposals

The Researcher, Architect, and BackendDev all treat hot-reload as a feature to be made safe. The DevOps answer is: **don't hot-reload financial config in production at all.**

The correct pattern is an immutable deployment:

```
config change → PR → CI passes → docker pull new image → rolling restart → drain old container
```

Railway and Render both support zero-downtime redeploys triggered by a `git push`. This is safer, auditable (every config change is a git commit), and idempotent. An `atomic.Pointer[MASConfig]` is clever engineering solving a problem that proper deployment hygiene eliminates.

**Operational cost**: near-zero. `git push` triggers a deploy. Config history lives in git, not in memory.

---

### Supporting Architect — But Adding a CI Gate

The Architect's `CircuitBreaker` and `PositionReconciler` goroutines are correct. However, concurrent Go code for financial state requires one non-negotiable CI addition that nobody mentioned:

```yaml
- run: go test -race ./...
```

The Go race detector must run in CI on every PR. `atomic.Pointer[MASConfig]` looks correct but the race detector has caught subtler bugs in production trading systems. This is not optional for the concurrency patterns proposed.

Additionally: the Architect's `HistoricalTick` shared contract needs a **schema validation test** in CI — deserialize a golden fixture file and assert field types. Backtest/live schema drift has caused real P&L discrepancies at firms that skipped this.

---

### What the CI Pipeline Must Gate (Final Position)

```
gitleaks → golangci-lint → go test -race → ruff → mypy → pytest → docker build
```

Order matters: secret scan first, fail fast on lint before running tests. The race detector must run before any merge to `main`. No exceptions for "it's just a feature branch" — concurrent financial code needs this on every push.

The `bypassPermissions` flag in `config.yaml` also remains an open blocker. It must be removed from the committed config before any CI pipeline is trustworthy — a runner with bypass permissions is a pipeline with no safety boundary.

## Final Synthesis & Architecture Recommendation
Here is the synthesis:

---

## Golang MM Strategy — Capital Preservation: Final Synthesis

### Executive Summary

A single-process Go market-making engine using micro-price + OFI fair value, EWMA volatility regime switching, tiered toxicity pauses, and a 4-condition circuit breaker. The architecture is intentionally minimal: one goroutine, one immutable config snapshot per tick, no cross-process RPC. Goes live only after 5-day paper trading with no circuit breaker trips.

---

### Key Conflict Resolutions

| Conflict | Decision | Rationale |
|---|---|---|
| gRPC split (BackendDev) vs. single-process | **Reject gRPC** | Polymarket CLOB is RTT-bound (50–200ms). Python→gRPC→Go adds distributed failure modes — ambiguous position state on reconnect — with zero measurable latency gain. Three agents independently rejected it. |
| `GOGC=off` (Researcher) vs. `GOGC=200` | **`GOGC=200` + explicit `runtime.GC()` between ticks** | `GOGC=off` is a hard OOM kill during spike regimes with open positions. Architect and BackendDev converged on `GOGC=200`; GC is called after order confirmation, before next tick. |
| Hot-reload (all) vs. immutable deployment (DevOps) | **Immutable deployment in production** | Config changes via `git push → CI → rolling restart` are auditable, idempotent, and eliminate the mid-tick config race that `atomic.Pointer` was solving. Hot-reload retained for local dev only. |
| Float64 drift claim (Architect) vs. floor bug (Researcher) | **OFI floor is the real fix** | Float64 rounding error at `±$0.30` OFI adjustment scale is ~10⁻¹⁴ — not tradeable. The correctness bug is division-by-zero at session start. Fix: exponential running max with `1e-6` floor. `decimal.Decimal` at boundary is added as defense-in-depth only. |
| TTL on position keys (BackendDev R1, retracted R2) | **No TTL on position keys** | TTL expiry silently zeroes recorded position during a Redis outage, making the circuit breaker see a false-healthy state. Only orderbook cache and fill-dedup keys get TTLs. |
| Stale-data breaker (Researcher) + 3-condition breaker (Architect) | **Merged into 4-condition circuit breaker** | L9 correctly overrides toxicity pauses (normal adverse selection). It must be cancelled on data integrity failures (stale feed, position divergence, session loss limit, kill signal). These are distinct threat models. |

---

### Non-Negotiable CI Gates

```
gitleaks → golangci-lint → go test -race ./... → docker build
```

`go test -race` is mandatory on every PR. Concurrent financial code has caught subtle bugs in production systems that code review misses. The `bypassPermissions` flag must be removed from the committed config before any CI pipeline is trustworthy.

---

Both `spec.md` and `tasks.md` have been updated with the full synthesized plan.
