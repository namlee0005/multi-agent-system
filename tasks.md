# MAS Strategy — Implementation Plan

**Strategy:** Capital Preservation Market Maker (`mas_strategy.go` + `mas_engine.go`)
**Spec:** `spec.md`

---

## Phase 1: Data Structures, Config & CI Foundation (Day 1)

### 1.1 Config & State Models
- [ ] Define `MASConfig` struct in `internal/strategy/mas_engine.go` with nested `FairValueConfig`, `VolatilityConfig`, `InventoryConfig`, `ToxicityConfig`, `CircuitBreakerConfig`, `ReconcilerConfig`
- [ ] `emergency_cap`, `max_inventory`, `max_loss_per_session` are read-only after startup — no mutation path in code
- [ ] Define `MASState` struct: `Regime`, `FairValue`, `OFINormalized`, `NetPosition`, `InventoryRatio`, `ToxicPausedSide`, `ToxicFillCount`, `EWMAVol`, `EWMAVar`, `SessionLoss`, `LastFeedTimestamp`, `CBTripCondition`
- [ ] All monetary fields use `decimal.Decimal` (shopspring/decimal) — enforce via code review
- [ ] Wire config to `config.yaml` under `mas:` key; validate at startup (panic on invalid values)
- [ ] Expose config via `atomic.Pointer[MASConfig]`; `OnTick` loads snapshot once at entry

### 1.2 Depth Level Enum
- [ ] Define `DepthLevel` (`L0`–`L9`) and `Side` (`Bid`/`Ask`) types
- [ ] Implement `PriceAtLevel(side Side, level DepthLevel, fairValue decimal.Decimal, spread decimal.Decimal) decimal.Decimal`

### 1.3 Shared Data Contract
- [ ] Define `HistoricalTick` struct: `Timestamp time.Time`, `Book OrderBook`, `Trades []Trade`, `Fills []Fill`
- [ ] Both backtest runner and live runner consume `<-chan HistoricalTick` — schema is locked here
- [ ] Add golden fixture file + schema validation test: deserialize fixture, assert all field types

### 1.4 CI Pipeline (non-negotiable gates)
- [ ] `.github/workflows/ci.yml`: `gitleaks → golangci-lint → go vet → go test -race ./... → docker build`
- [ ] `go test -race ./...` runs on every PR; concurrent financial state requires this
- [ ] Remove `bypassPermissions` from committed `config.yaml`; move to local dev env var only
- [ ] Add `logs/` and `.env` to `.gitignore`; commit `.env.example` with placeholder values

**Milestone:** Config loads, structs compile, all types defined, CI pipeline green.

---

## Phase 2: Fair Value Engine (Day 2)

### 2.1 Micro-Price
- [ ] Implement `ComputeMicroPrice(bestBid, bestAsk decimal.Decimal, bidQty, askQty decimal.Decimal) decimal.Decimal`
- [ ] Formula: `(bestAsk × bidQty + bestBid × askQty) / (bidQty + askQty)`
- [ ] Unit test: balanced book → returns mid-price; imbalanced book → pulls toward heavier side

### 2.2 OFI Calculation (Decimal boundary enforced)
- [ ] Implement `OFITracker` with `Add(trade Trade)` and `Normalized() decimal.Decimal` methods
- [ ] Internal accumulation in `float64` (performance); exponential running max with `1e-6` floor (prevents init division instability)
- [ ] `Normalized()` converts to `decimal.Decimal` at the boundary — this is the **only** exit point; no `float64` OFI value may be passed into price math
- [ ] Unit test: buy-heavy sequence → positive OFI; sell-heavy → negative; decay resets toward zero; first-tick normalization does not panic or return extreme value
- [ ] Code review gate: any function receiving OFI output must accept `decimal.Decimal`, not `float64`

### 2.3 Fair Value Combinator
- [ ] `ComputeFairValue(microPrice decimal.Decimal, ofiNorm decimal.Decimal, cfg FairValueConfig) decimal.Decimal`
- [ ] `fair_value = micro_price + ofi_normalized × ofi_alpha × tick_size`

**Milestone:** `ComputeFairValue` returns correct values across unit tests for all OFI extremes including session-start edge case.

---

## Phase 3: Volatility Regime Classifier (Day 3)

### 3.1 EWMA Volatility (replaces rolling stddev as default)
- [ ] Implement `VolatilityTracker` with EWMA core:
  - `Update(midPrice float64)` — computes `log_return`, updates `ewma_var` via `λ × prev + (1-λ) × return²`
  - `EWMAVol() float64` — returns `sqrt(ewma_var)`
  - `λ` derived from `ewma_halflife` config: `λ = exp(-ln(2) / halflife_seconds)`
- [ ] Default `ewma_halflife: 15s` (λ ≈ 0.955); configurable per instrument
- [ ] Rolling-window stddev retained as fallback path behind `vol_use_ewma: false` config flag
- [ ] Unit test: flat prices → near-zero vol; step-change → EWMA responds within 2× halflife (30s); boundary: no thrashing between regimes at threshold
- [ ] Benchmark test: EWMA spike detection fires < 30s vs. 60s rolling on same synthetic flash-crash series

### 3.2 Regime FSM
- [ ] Implement `ClassifyRegime(vol float64, current VolatilityRegime, cfg VolatilityConfig) VolatilityRegime`
- [ ] Hysteresis: enter Spike at `vol_threshold`, exit at `vol_exit_threshold`
- [ ] Unit test: confirm no thrashing at boundary values; EWMA 15s halflife fires within 30s of simulated flash crash

**Milestone:** Regime switches correctly on simulated price series; EWMA confirmed faster than 60s rolling for spike detection.

---

## Phase 4: Quote Generator (Days 4–5)

### 4.1 Sideways Quote Builder
- [ ] `BuildSidewaysQuotes(state MASState, cfg MASConfig) []Order`
- [ ] L1–L5 uniform sizing, skew applied
- [ ] Unit test: long inventory → bid prices shift down; short → ask prices shift up

### 4.2 Spike Quote Builder
- [ ] `BuildSpikeQuotes(state MASState, cfg MASConfig) []Order`
- [ ] L0–L3: `spike_near_spread_multiplier × base_spread`, `spike_near_size_ratio` sizes
- [ ] L4: always empty (buffer zone — enforced by test)
- [ ] L5–L9: `spike_deep_offset_ticks` below fair value, `spike_deep_size_ratio` sizes
- [ ] Unit test: verify L4 always empty; L0 spread ≥ 4× base spread; L5–L9 sizes ≥ L0–L3 sizes

### 4.3 Skew Application
- [ ] `ApplyInventorySkew(orders []Order, inventoryRatio float64, cfg InventoryConfig) []Order`
- [ ] Unit test: at `inventory_ratio = 1.0`, skew = `max_skew_ticks` applied to both sides

### 4.4 Emergency Cap Handler
- [ ] `CheckEmergencyCap(netPosition decimal.Decimal, cfg InventoryConfig) (cancelBids, cancelAsks bool)`
- [ ] Unit test: position > `emergency_cap` → returns `cancelBids=true`

**Milestone:** Quote builder returns correct order sets for Sideways + Spike + extreme inventory.

---

## Phase 5: Toxicity Monitor + Circuit Breaker (Day 6)

### 5.1 Fill Evaluator
- [ ] `EvaluateFill(fill Fill, priceHistory PriceHistory, cfg ToxicityConfig) bool`
- [ ] Returns `true` if price moved `toxic_move_ticks` against fill within `toxic_detection_window`
- [ ] `toxic_detection_window` is configurable per regime (Spike regime uses longer window)

### 5.2 Tiered Pause Manager
- [ ] `ToxicityPauseManager.RecordFill(side Side, isToxic bool) time.Duration`
- [ ] Returns pause duration based on rolling count tier (0s / 15s / 45s / 120s)
- [ ] `IsPaused(side Side) bool` — checks `ToxicPausedSide` expiry
- [ ] L9 compliance anchor remains active during toxicity pause (normal adverse selection)
- [ ] Unit test: 6 toxic fills → 120s pause; only bid paused, ask still active

### 5.3 Circuit Breaker (cancels ALL including L9)
- [ ] `CircuitBreaker` struct with `Trip(condition string)` and `IsTripped() bool` methods
- [ ] Four independent trip conditions — each must be testable in isolation:
  1. `SessionLoss > max_loss_per_session` (from config; `decimal.Decimal` comparison)
  2. `PositionReconciler` delta > `max_drift_threshold` for ≥ `max_consecutive_miss` consecutive 5s cycles
  3. No feed update for > `stale_feed_timeout` seconds (`time.Since(state.LastFeedTimestamp) > timeout`)
  4. `SIGUSR1` signal received OR `/tmp/mas_kill` file present at tick entry
- [ ] Trip action: return `CancelAll{}` immediately; set `CBTripCondition`; log trip condition + timestamp + last feed time
- [ ] Unit test: each of the 4 conditions independently trips the breaker and cancels all orders including L9
- [ ] Recovery: manual operator restart OR auto-reconnect with 10s cooldown; CB does not self-clear

### 5.4 Stale-Data Circuit Breaker (condition 3 — explicit implementation steps)
- [ ] `MASState.LastFeedTimestamp` updated to `time.Now()` on every received `HistoricalTick` or live market event
- [ ] At start of `OnTick`, before any computation: check `time.Since(state.LastFeedTimestamp) > cfg.CircuitBreaker.StaleFeedTimeout`
- [ ] If stale: call `circuitBreaker.Trip("stale_feed")`, return `[]OrderAction{CancelAll{}}`
- [ ] Log entry includes: trip condition, `LastFeedTimestamp`, `time.Now()`, computed staleness duration
- [ ] Unit test: mock feed that stops updating → CB trips after `stale_feed_timeout`; resumes after reconnect + cooldown
- [ ] Integration test: WebSocket drop simulation → confirms CancelAll issued within 1 tick of timeout expiry

### 5.5 Position Reconciler (condition 2 — explicit implementation steps)
- [ ] `PositionReconciler` goroutine launched at strategy startup; runs independently of tick loop
- [ ] Every `reconciler.poll_interval` (default 5s): call `exchangeAdapter.FetchPosition() decimal.Decimal`
- [ ] Compute `delta = abs(exchangePos - state.NetPosition)`; compare against `cfg.Reconciler.MaxDriftThreshold`
- [ ] If `delta > threshold`: increment `consecutiveMiss`; else reset to 0
- [ ] If `consecutiveMiss >= cfg.Reconciler.MaxConsecutiveMiss`: call `circuitBreaker.Trip("position_drift")`
- [ ] Log every reconciler cycle: `exchange_pos`, `local_pos`, `delta`, `consecutive_miss`, timestamp
- [ ] **Redis position keys have no TTL** — written once per fill confirmation; zeroed only when both local and exchange positions confirm flat
- [ ] Reconciler does NOT auto-correct `NetPosition` — CB trip only; human restart required
- [ ] Unit test: inject 3 consecutive reconciler cycles with delta > threshold → CB trips; 2 cycles does not trip; gap in drift resets counter
- [ ] Integration test: simulate fill dropped by exchange adapter → reconciler detects divergence within 3 × `poll_interval`

**Milestone:** Toxicity detection fires correctly; circuit breaker trips on all 4 conditions independently; stale-feed detection fires within 1 tick of timeout; position reconciler detects and reports divergence within 15s.

---

## Phase 6: Strategy Orchestrator (Day 7)

### 6.1 `mas_strategy.go` Main Loop
- [ ] `MASStrategy.OnTick(book OrderBook, trades []Trade, fills []Fill) []OrderAction`
- [ ] Sequence: `cfg := cfgPtr.Load()` → check stale feed CB → update `LastFeedTimestamp` → update OFI → compute fair value → classify regime (EWMA) → build quotes → apply skew → check emergency cap → check session loss CB → check toxicity pauses → send orders → `runtime.GC()`
- [ ] GC is called after order confirmation, before waiting for next tick (`GOGC=200`)
- [ ] `OrderAction` union type: `Place(order)`, `Cancel(id)`, `CancelSide(side)`, `CancelAll`

### 6.2 Integration
- [ ] Wire `MASStrategy` into exchange adapter (same interface as existing strategies)
- [ ] Log state snapshot per tick to `session-{id}.json`: regime, fair_value, ofi, ewma_vol, inventory, paused_sides, circuit_breaker_state, last_feed_timestamp, reconciler_delta

### 6.3 Deployment (immutable — no hot-reload in production)
- [ ] Config changes go through: PR → CI passes → `docker pull new image` → rolling restart
- [ ] `atomic.Pointer[MASConfig]` exists for local dev/testing only; production path is image rollout
- [ ] Document deployment procedure in `docs/OPERATIONS.md`

**Milestone:** Strategy compiles, runs dry against recorded market data, GC timing measured between ticks.

---

## Phase 7: Backtesting & Calibration (Days 8–9)

- [ ] Run against 7-day historical `HistoricalTick` stream (calm + 3 spike events minimum)
- [ ] Measure: fill rate at L0–L3 vs. L5–L9 during spike events; inventory excursion max; toxic fill rate before/after pause; circuit breaker false-positive rate; EWMA regime-switch latency vs. rolling-window baseline
- [ ] Calibrate `ofi_alpha`, `vol_threshold`, `spike_near_size_ratio`, `spike_deep_size_ratio`, `ewma_halflife`, `stale_feed_timeout`, `max_drift_threshold` per instrument
- [ ] Target: zero fills at L0–L3 during confirmed spike; inventory within `max_inventory` 99% of time; no circuit breaker trips on clean data; EWMA spike detection < 30s

---

## Phase 8: Paper Trading (Days 10–14)

- [ ] Deploy against live feed with simulated order execution (no real capital)
- [ ] Monitor: PnL attribution (OFI edge, spread capture, inventory carry), regime transition frequency, toxicity pause triggers, reconciler delta distribution, stale-feed event count
- [ ] Fix any edge cases; freeze config values before going live
- [ ] **Go/no-go gate**: 5 consecutive trading days, no circuit breaker trips, inventory within bounds 99%+ of time, reconciler delta < threshold 99.9% of cycles

---

## Milestones Summary

| Milestone | Target | Definition of Done |
|-----------|--------|-------------------|
| M1: Foundation | Day 1 | Types compile, CI pipeline green, race detector enabled |
| M2: Fair Value | Day 2 | `ComputeFairValue` unit tests pass; OFI Decimal boundary enforced |
| M3: Regime | Day 3 | EWMA FSM hysteresis tests pass; spike detection < 30s vs. 60s rolling |
| M4: Quotes | Day 5 | Sideways + Spike builders verified; L4 empty enforced |
| M5: Capital Protection | Day 6 | Toxicity pauses + 4-condition CB + stale-feed CB + reconciler all tested independently |
| M6: Live Dry Run | Day 7 | Strategy runs on recorded data; GC between ticks confirmed |
| M7: Backtested | Day 9 | Calibrated config; zero L0–L3 fills in spike events; no CB false positives |
| M8: Paper Live | Day 14 | 5-day paper run; no CB trips; reconciler delta clean; go/no-go decision |
