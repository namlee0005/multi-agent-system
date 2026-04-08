# Golang MM Strategy — Capital Preservation Specification

## Executive Summary

A single-process Go market-making engine for capital preservation on Polymarket's CLOB. The strategy uses micro-price + OFI fair value, EWMA volatility regime switching (Sideways/Spike), tiered toxicity pauses for adverse selection defense, and a 4-condition circuit breaker as the hard capital boundary. The execution model is a single `OnTick` goroutine consuming an immutable config snapshot — no mid-tick state mutation, no cross-process RPC. Config changes deploy via immutable image rollout, not hot-reload. The system goes live only after passing 5-day paper trading with acceptable PnL variance.

**Key resolved debates:**
- **Reject gRPC split**: Polymarket CLOB tick rates are RTT-bound (50–200ms), not compute-bound. A Python→gRPC→Go boundary adds distributed failure modes with zero measurable latency gain. Single-process Go.
- **Reject `GOGC=off`**: Unbounded heap growth with open positions is a hard kill risk. Use `GOGC=200` + explicit `runtime.GC()` between ticks.
- **Reject hot-reload in production**: Immutable deployment (git push → CI → rolling restart) is safer, auditable, and eliminates the mid-tick config race entirely.
- **No TTL on position keys**: Position state never expires. Only orderbook snapshot cache and fill-dedup keys get TTLs.

---

## Recommended Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Runtime | Go 1.22+ | Deterministic goroutine scheduling; `shopspring/decimal` for monetary precision; no GIL |
| Decimal math | `shopspring/decimal` | ~10–20× slower than float64 but correct; all monetary fields use this |
| OFI accumulator | `float64` (internal) + `decimal.Decimal` boundary | Float64 carries 15–17 sig digits; rounding error at OFI adjustment scale (~$0.30 max) is ~10⁻¹⁴ — real risk is division-by-zero at init, not drift |
| Config | `viper` + env | 12-factor; no hot-reload in prod — config changes trigger image rollout |
| Position state | Redis (`go-redis`), no TTL on position keys | Sub-second stop-loss checks; TTL only on orderbook cache + fill-dedup keys |
| GC tuning | `GOGC=200` + `runtime.GC()` between ticks | Deterministic on critical path; no OOM risk vs. `GOGC=off` |
| Concurrency | `atomic.Pointer[MASConfig]` snapshot per tick | Config loaded once at tick entry; immutable through pipeline |
| CI gate | `go test -race ./...` mandatory | Race detector on every PR; concurrent financial state has subtle bugs |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Single Go Process                            │
│                                                                 │
│  config.yaml ──► atomic.Pointer[MASConfig]                      │
│                         │                                       │
│  CLOB WebSocket ──► OnTick(book, trades, fills)                 │
│                         │                                       │
│                    cfg := cfgPtr.Load()  ← snapshot once        │
│                         │                                       │
│          ┌──────────────┼──────────────────┐                    │
│          ▼              ▼                  ▼                    │
│    OFITracker     VolatilityTracker   PositionReconciler        │
│    (float64       (EWMA, 15s          (5s REST poll;            │
│     internal;      halflife;           delta > threshold        │
│     decimal        hysteresis          → circuit breaker)       │
│     boundary)      FSM)                                         │
│          │              │                                       │
│          └──────────────┘                                       │
│                    ▼                                            │
│              ComputeFairValue                                   │
│                    │                                            │
│         ┌──────────┴──────────┐                                 │
│         ▼                     ▼                                 │
│   BuildSidewaysQuotes    BuildSpikeQuotes                       │
│   (L1–L5 uniform)        (L0–L3 near; L4 empty;                 │
│                           L5–L9 deep)                           │
│         │                     │                                 │
│         └──────────┬──────────┘                                 │
│                    ▼                                            │
│             ApplyInventorySkew                                  │
│                    │                                            │
│             ToxicityPauseManager                                │
│             (side-specific; 15s/45s/120s tiers)                 │
│                    │                                            │
│             CircuitBreaker (4 conditions)                       │
│             1. Session loss > max_loss_per_session              │
│             2. Recon delta > threshold for 3+ cycles            │
│             3. Stale feed (no update > N seconds) → cancel ALL  │
│             4. SIGUSR1 or /tmp/mas_kill file                    │
│                    │                                            │
│                    ▼                                            │
│             []OrderAction → Exchange Adapter                    │
│                    │                                            │
│             runtime.GC()  ← explicit, between ticks            │
│                                                                 │
│  session-{id}.json (structured log per tick)                    │
└─────────────────────────────────────────────────────────────────┘
```

### Canonical Data Types

```go
type HistoricalTick struct {
    Timestamp time.Time
    Book      OrderBook
    Trades    []Trade
    Fills     []Fill  // empty slice for backtest
}
// Backtest runner and live runner both consume <-chan HistoricalTick.
// No schema divergence between environments.
```

### Capital Preservation Invariants

1. **L9 compliance anchor is cancelled on stale feed** — L9 is only overridden for normal toxicity pauses; data integrity failures cancel everything
2. **`emergency_cap`, `max_inventory`, compliance params are immutable at runtime** — require full image rollout to change
3. **Position state has no TTL** — write-once-per-fill; zeroed only on confirmed flat + reconciler agreement
4. **OFI normalization floor** — exponential running max with `1e-6` floor prevents division instability at session start
