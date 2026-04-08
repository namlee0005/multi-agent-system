# MAS Strategy — Capital Preservation Market Maker

**Motto:** _"Không thua tiền là được"_ — Just don't lose money.
**Date:** 2026-04-01
**Files:** `internal/strategy/mas_strategy.go`, `internal/strategy/mas_engine.go`

---

## 1. Design Philosophy

This strategy is **not** a PnL-maximizer. It is a **loss-minimizer**. Every algorithm choice optimizes for one thing first: avoid giving money to informed flow. Profit is a side effect of surviving long enough.

The four pillars:
1. **Fair Value** — Quote around a smarter mid, not the naive mid.
2. **Volatility Regime** — Behave differently when the market is moving fast.
3. **Inventory Control** — Never let inventory drift into unhedgeable territory.
4. **Toxicity Pause** — If you got hit by informed flow, stop feeding that side.

---

## 2. Pillar 1: Fair Value (Micro-Price + OFI)

### 2.1 Micro-Price

The naive mid-price `(best_bid + best_ask) / 2` ignores orderbook imbalance. A better fair value estimate is the **volume-weighted mid**:

```
micro_price = (best_ask × bid_qty + best_bid × ask_qty) / (bid_qty + ask_qty)
```

This pulls the fair value toward the side with more liquidity — if there are 10x more bids than asks at the top of book, the true fair value is closer to the ask.

### 2.2 OFI Adjustment

Order Flow Imbalance (OFI) measures net directional pressure from recent trades:

```
ofi = Σ (buy_volume - sell_volume) over last N seconds
ofi_normalized = ofi / max_observed_ofi   ∈ [-1.0, +1.0]
```

The final fair value used for quoting:

```
fair_value = micro_price + (ofi_normalized × ofi_alpha × tick_size)
```

- `ofi_alpha` defaults to `3.0` ticks — calibrate per instrument.
- Positive OFI → fair value shifts up → bid shallower, ask tighter.
- Negative OFI → fair value shifts down → bid tighter, ask shallower.

**Decimal Precision Rule (approved):** OFI accumulation runs in `float64` for performance. The `Normalized()` boundary method converts to `decimal.Decimal` before the value is multiplied into any price. The running max denominator has a `1e-6` floor to prevent division instability at session start. **No `float64` value ever touches a price or monetary field directly.**

**Config:**
```yaml
mas:
  fair_value:
    ofi_window: 10s
    ofi_alpha: 3.0
    ofi_decay: 0.85   # Exponential decay per second
```

---

## 3. Pillar 2: Volatility Regime

Two regimes: **Sideways** and **Spike**.

### 3.1 Regime Detection — EWMA Volatility (approved)

Volatility is estimated using **Exponentially Weighted Moving Average (EWMA)** rather than a fixed rolling window. EWMA reacts to a flash crash within 2× the halflife (default 15s), making spike detection ~4× faster than the legacy 60s rolling stddev.

```
# EWMA volatility update (per tick)
log_return = ln(mid_price[t] / mid_price[t-1])
ewma_var   = λ × ewma_var_prev + (1 - λ) × log_return²
ewma_vol   = sqrt(ewma_var)

# λ derived from halflife:
λ = exp(-ln(2) / halflife_seconds)   # halflife=15s → λ ≈ 0.955
```

| Condition | Regime |
|-----------|--------|
| `ewma_vol < vol_threshold` | Sideways |
| `ewma_vol >= vol_threshold` | Spike |

`vol_threshold` defaults to `0.0025` (0.25% per minute). Hysteresis: enter Spike at 0.0025, exit at 0.0015 — prevents thrashing.

The rolling-window stddev is retained as a fallback controlled by `vol_use_ewma: true` (default). Both paths produce `float64`; neither touches monetary fields.

### 3.2 Sideways Quoting (Normal)

Standard symmetric quoting around `fair_value`. Spread = `base_spread`. Sizes uniform across L1–L5.

```
bid_price[L] = fair_value - base_spread/2 - (L × tick_size × level_step)
ask_price[L] = fair_value + base_spread/2 + (L × tick_size × level_step)
size[L] = base_size
```

### 3.3 Spike Quoting — Spread Widening Math

When `regime == Spike`, `base_spread` is multiplied by `spike_near_spread_multiplier` for near-touch levels L0–L3:

```
# Step 1: Compute widened effective spread
effective_spread = base_spread × spike_near_spread_multiplier

# Example: base_spread = 0.0004 (4 bps), spike_near_spread_multiplier = 4.0
#          → effective_spread = 0.0016 (16 bps)

# Step 2: Place near-touch quotes at widened half-spread
bid_price[L] = fair_value - (effective_spread / 2) - (L × wide_step × tick_size)
ask_price[L] = fair_value + (effective_spread / 2) + (L × wide_step × tick_size)

# Step 3: Thin the size at near-touch
size[L] = base_size × spike_near_size_ratio   # e.g. 0.20 → 20% of normal
```

The full spike layout:

```
L0–L3 (Near Touch): widened spread + thinned size
  half_spread = (base_spread × spike_near_spread_multiplier) / 2
  bid_price[L] = fair_value - half_spread - (L × wide_step × tick_size)
  ask_price[L] = fair_value + half_spread + (L × wide_step × tick_size)
  size[L]      = base_size × spike_near_size_ratio

L4 (Buffer): Empty — no orders placed at this level

L5–L9 (Deep Catch): deep offset + thick size — catches over-extended moves
  bid_price[L] = fair_value - spike_deep_offset_ticks × tick_size - ((L-5) × level_step × tick_size)
  ask_price[L] = fair_value + spike_deep_offset_ticks × tick_size + ((L-5) × level_step × tick_size)
  size[L]      = base_size × spike_deep_size_ratio   # e.g. 1.50 → 150% of normal
```

**Numeric example** (BTC, tick = $0.10, base_spread = $2.00):

| Level | Regime | Bid Offset from FV | Size Ratio |
|-------|--------|--------------------|------------|
| L0 | Sideways | −$1.00 | 1.0× |
| L0 | Spike | −$4.00 (4× widened) | 0.20× |
| L4 | Spike | — (empty buffer) | 0 |
| L5 | Spike | −$15.00 (deep_offset_ticks=150) | 1.50× |
| L9 | Spike | −$15.40 + compliance anchor (see §7) | 1.50× |

**Rationale:** L0–L3 catches noise fills from informed flow — unprofitable. L5–L9 only fills on genuine over-extension (panic dumps/pumps) — these fills mean-revert.

**Config:**
```yaml
mas:
  volatility:
    vol_threshold: 0.0025
    vol_exit_threshold: 0.0015
    vol_window: 60s           # fallback rolling window (vol_use_ewma: false)
    vol_use_ewma: true        # default: EWMA
    ewma_halflife: 15s        # λ derived from this
    base_spread: 0.0004              # 4 bps; monetary fields use Decimal
    spike_near_spread_multiplier: 4.0
    spike_near_size_ratio: 0.20
    wide_step: 2                     # ticks between near-touch levels
    spike_deep_offset_ticks: 150     # L5 sits 150 ticks below fair value
    spike_deep_size_ratio: 1.50
    level_step: 1                    # ticks between deep levels L5–L9
```

---

## 4. Pillar 3: Inventory Control

### 4.1 Inventory Skew

When inventory deviates from zero, skew quotes to mean-revert it:

```
inventory_ratio = net_position / max_inventory   ∈ [-1.0, +1.0]
skew_ticks = inventory_ratio × max_skew_ticks

bid_price[L] -= skew_ticks × tick_size   # Long → lower bids (discourage buying)
ask_price[L] -= skew_ticks × tick_size   # Long → lower asks (encourage selling)
```

- `max_skew_ticks` defaults to `5`. At max inventory, bids and asks both shift 5 ticks down — hard asymmetric pressure to sell.
- Skew applies in **both** Sideways and Spike regimes.

### 4.2 Hard Inventory Caps

```yaml
mas:
  inventory:
    max_inventory: 1000        # Hard cap in base units (Decimal)
    max_skew_ticks: 5
    emergency_cap: 1200        # If exceeded: cancel one side entirely
    emergency_side_cancel: true
```

When `abs(net_position) > emergency_cap`:
- If long beyond cap → cancel ALL bids immediately; only asks remain.
- If short beyond cap → cancel ALL asks immediately; only bids remain.

This is the last line of defense against a runaway position.

---

## 5. Pillar 4: Toxicity Pause

### 5.1 Detection

A fill is **toxic** if price moved adversely by more than `toxic_move_ticks` within `toxic_detection_window` after the fill:

```go
if priceMovedAgainst(fill, toxicMoveTicks, toxicWindow) {
    toxicFillCount[side]++
    if toxicFillCount[side] >= tier3Count {
        pauseSide(side, tier3Pause)
    } else if toxicFillCount[side] >= tier2Count {
        pauseSide(side, tier2Pause)
    } else if toxicFillCount[side] >= tier1Count {
        pauseSide(side, tier1Pause)
    }
}
```

### 5.2 Pause Behavior

During a toxicity pause on side `S`:
- All orders on side `S` are cancelled immediately.
- No new orders placed on side `S` for `N` seconds.
- The opposite side continues quoting normally.

### 5.3 Tiered Pause Duration

| Toxic Fill Count (rolling 5 min) | Pause Duration |
|----------------------------------|---------------|
| 2–3 fills | 15s |
| 4–5 fills | 45s |
| 6+ fills | 120s |

**Config:**
```yaml
mas:
  toxicity:
    toxic_move_ticks: 3
    toxic_detection_window: 8s
    tier1_count: 2
    tier1_pause: 15s
    tier2_count: 4
    tier2_pause: 45s
    tier3_count: 6
    tier3_pause: 120s
    rolling_window: 300s
```

---

## 6. Data Structures

```go
// mas_engine.go

type MASConfig struct {
    FairValue      FairValueConfig
    Volatility     VolatilityConfig
    Inventory      InventoryConfig
    Toxicity       ToxicityConfig
    Compliance     ComplianceConfig
    CircuitBreaker CircuitBreakerConfig
    Reconciler     ReconcilerConfig
}

type MASState struct {
    Regime              VolatilityRegime
    FairValue           decimal.Decimal
    OFINormalized       float64         // float64 internally; Decimal at price boundary
    NetPosition         decimal.Decimal
    InventoryRatio      float64
    ToxicPausedSide     map[Side]time.Time
    ToxicFillCount      map[Side]int
    EWMAVol             float64         // current EWMA volatility estimate
    EWMAVar             float64         // running variance accumulator (λ-weighted)
    SessionLoss         decimal.Decimal
    LastFeedTimestamp   time.Time       // used by stale-data circuit breaker
    CBTripCondition     string          // non-empty when circuit breaker is tripped
}

type CircuitBreakerConfig struct {
    MaxLossPerSession   decimal.Decimal // e.g. 500 USDT
    MaxDriftThreshold   decimal.Decimal // max position delta before CB trip
    StaleFeedTimeout    time.Duration   // e.g. 5s
}

type ReconcilerConfig struct {
    PollInterval        time.Duration   // e.g. 5s
    MaxDriftThreshold   decimal.Decimal // same as CB, reconciler owns detection
    MaxConsecutiveMiss  int             // e.g. 3 consecutive cycles before CB trip
}

type VolatilityRegime int

const (
    RegimeSideways VolatilityRegime = 0
    RegimeSpike    VolatilityRegime = 1
)

type DepthLevel int // L0–L9

type Side int

const (
    Bid Side = 0
    Ask Side = 1
)
```

---

## 7. Exchange Compliance (Fat-Tail)

### 7.1 SLA Requirement

The exchange requires **continuous liquidity within ±2% of fair value** (depth SLA). Failure to post inside this band counts as a liquidity breach. Three breaches in a rolling 24-hour window trigger a maker-fee penalty.

### 7.2 L9 Static Anchor at 1.95%

To guarantee the exchange always sees a valid deep quote, **L9 is statically anchored at exactly 1.95% from fair value**, regardless of regime or spike depth calculations:

```
# Static anchor — computed first, before any regime logic
l9_anchor_bid = fair_value × (1 - 0.0195)   # = fair_value − 1.95%
l9_anchor_ask = fair_value × (1 + 0.0195)   # = fair_value + 1.95%

# Compliance enforcement: L9 price is the MAX (bid) / MIN (ask) of:
#   (a) the price produced by the normal depth formula
#   (b) the static anchor
bid_price[L9] = max(l9_anchor_bid,  formula_bid_price[L9])
ask_price[L9] = min(l9_anchor_ask,  formula_ask_price[L9])
```

This clamps L9 **no deeper than 1.95%** from fair value in all market conditions. During extreme spikes, the spike depth formula may push L9 beyond 2% — the anchor overrides it.

### 7.3 Why 1.95% (Not 2.00%)

A 5 bps safety margin accounts for:
- Latency between fair value computation and order placement (~50–100ms at peak load)
- Fair value drift during order propagation
- Rounding from tick-size quantization

A quote placed at exactly 2.00% that drifts 1 tick due to latency becomes a breach. The 1.95% anchor makes compliance structurally guaranteed rather than dependent on timing.

### 7.4 L9 Size Floor

L9 must also meet a **minimum notional size** to count as valid liquidity under the SLA:

```yaml
mas:
  compliance:
    l9_anchor_pct: 0.0195          # 1.95% static anchor
    l9_min_notional: 500.0         # Minimum USD notional at L9
    l9_enabled: true               # If false, L9 is skipped (never breach-safe)
```

### 7.5 Integration in Quote Flow

```
every tick (after regime + skew + toxicity checks):
  1. Compute all L0–L8 prices via normal formula
  2. Compute l9_anchor_bid = fair_value × (1 - compliance.l9_anchor_pct)
     Compute l9_anchor_ask = fair_value × (1 + compliance.l9_anchor_pct)
  3. bid_price[L9] = max(l9_anchor_bid, formula_bid[L9])
     ask_price[L9] = min(l9_anchor_ask, formula_ask[L9])
  4. size[L9]     = max(base_size × spike_deep_size_ratio, l9_min_notional / fair_value)
  5. Place L9 regardless of toxicity pause — compliance overrides pause on this level only
```

> **Non-negotiable:** L9 orders are placed even during a toxicity pause. Toxicity pauses suppress L0–L8 on the affected side; L9 remains live to maintain exchange compliance.

---

## 8. Quote Generation Flow

```
every tick:
  1. micro_price   = (best_ask × bid_qty + best_bid × ask_qty) / (bid_qty + ask_qty)
  2. ofi_float     = exponential_decay_ofi (float64)
     ofi_normalized = Decimal(ofi_float / max_ofi)   ∈ [-1, +1]  ← Decimal boundary
  3. fair_value    = micro_price + ofi_normalized × ofi_alpha × tick_size
  4. log_return    = ln(mid_price[t] / mid_price[t-1])
     ewma_var      = λ × ewma_var_prev + (1-λ) × log_return²
     ewma_vol      = sqrt(ewma_var)                              ← EWMA (float64)
  5. regime        = hysteresis_fsm(ewma_vol)
  6. inventory_ratio = net_position / max_inventory
  7. skew_ticks    = inventory_ratio × max_skew_ticks

  if regime == Sideways:
    quote L1–L5 at base_spread/2 + skew
  elif regime == Spike:
    quote L0–L3 at (base_spread × spike_near_spread_multiplier)/2 + skew, thin size
    skip L4
    quote L5–L9 at spike_deep_offset + skew, thick size

  apply L9 compliance anchor (clamp to ±1.95%)
  apply emergency cap (cancel one side if beyond emergency_cap)
  apply toxicity pauses (suppress L0–L8 on paused side; L9 stays)
  check circuit breaker (stale feed, reconciler delta, session loss, kill signal)
```

---

## 9. Capital Preservation Mechanics (Approved — 2026-04-01)

These four mechanics were reviewed and approved by debate consensus. They are mandatory; no `--skip` flag exists for any of them.

### 9.1 EWMA Volatility (replaces rolling stddev)

**Problem:** A 60s rolling window has 60s of lag. During a flash crash, the strategy remains in Sideways regime for up to a full minute, posting tight spreads into an adverse move.

**Solution:** EWMA with `halflife=15s` (λ ≈ 0.955). The estimator responds within 30s of a sudden volatility jump — before the Spike regime would matter. The rolling window is retained as a config-selectable fallback (`vol_use_ewma: false`) for calibration comparison only.

**Implementation boundary:** `VolatilityTracker.EWMAVol()` returns `float64`. It is used only for regime classification (comparison against `vol_threshold`). It never enters a price formula directly.

### 9.2 Decimal Precision for OFI

**Problem:** OFI accumulates as `float64` sums of trade volumes. Passing this raw `float64` into `fair_value` computations via `ofi_normalized × ofi_alpha × tick_size` silently introduces floating-point drift into the final price `decimal.Decimal`.

**Solution:** `OFITracker.Normalized()` is the single exit point for OFI. It returns `decimal.Decimal`. All upstream accumulation (sum, max-tracking, decay) remains `float64` for throughput. The conversion at this boundary is the only place floating-point OFI touches a Decimal price chain.

**Rule:** Any function whose return value will be added to or multiplied with a `decimal.Decimal` price must return `decimal.Decimal`. Enforced by code review.

### 9.3 Stale-Data Circuit Breaker

**Problem:** If the exchange feed silently drops (network partition, WebSocket timeout without close frame), the strategy continues quoting against stale prices — effectively quoting into a market it cannot see.

**Solution:** Every tick records `MASState.LastFeedTimestamp = time.Now()`. At tick entry, before any computation:

```go
if time.Since(state.LastFeedTimestamp) > cfg.CircuitBreaker.StaleFeedTimeout {
    circuitBreaker.Trip("stale_feed: no update for Xs")
    return CancelAll{}
}
```

- `stale_feed_timeout` defaults to `5s`.
- Trip action: cancel ALL orders including L9; halt placement; log trip with timestamp and last-seen feed time.
- Recovery: manual operator restart OR automated reconnect with 10s cool-down before resuming quotes.
- L9 compliance note: the exchange SLA does not penalize for absence during a confirmed feed outage (documented in exchange API terms). CB cancels L9 in this condition.

**Config:**
```yaml
mas:
  circuit_breaker:
    stale_feed_timeout: 5s
    max_loss_per_session: 500.0   # USDT; Decimal
```

### 9.4 Position Reconciler

**Problem:** Local fill accounting (`MASState.NetPosition`) can diverge from the exchange's actual position due to: dropped fill confirmations, partial fills miscounted, or race conditions during order cancellation. Trading on a wrong position belief leads to unhedged risk.

**Solution:** A background goroutine polls the exchange REST position endpoint every 5s and compares against `MASState.NetPosition`:

```go
// reconciler goroutine (runs independently of tick loop)
for range ticker.C {
    exchangePos := fetchExchangePosition()
    delta := abs(exchangePos - state.NetPosition)
    if delta > cfg.Reconciler.MaxDriftThreshold {
        consecutiveMiss++
        if consecutiveMiss >= cfg.Reconciler.MaxConsecutiveMiss {
            circuitBreaker.Trip("position_drift: delta=X for N consecutive cycles")
        }
    } else {
        consecutiveMiss = 0
    }
}
```

- `max_drift_threshold` defaults to `10` base units (instrument-specific; calibrate per asset).
- `max_consecutive_miss` defaults to `3` (i.e., 15s of continuous divergence before trip).
- **Position keys in Redis have no TTL** — write-once per fill; zeroed only on confirmed flat with reconciler agreement on both sides.
- The reconciler does not correct `NetPosition` automatically — it only trips the circuit breaker. Human review is required before restart.

**Config:**
```yaml
mas:
  reconciler:
    poll_interval: 5s
    max_drift_threshold: 10        # base units; instrument-specific
    max_consecutive_miss: 3
```

---

## 10. Risk Invariants (Non-Negotiable)

1. **Fair value always uses micro-price + OFI — never raw mid-price.**
2. **In Spike regime, L0–L3 effective spread = `base_spread × spike_near_spread_multiplier`.**
3. **L5–L9 orders exist in Spike regime — bot never fully disappears from depth.**
4. **L9 bid/ask is always clamped to within 1.95% of fair value (exchange compliance).**
5. **L9 is placed even during toxicity pauses — compliance overrides pause at this level.**
6. **Inventory beyond `emergency_cap` → immediate one-sided cancel of L0–L8.**
7. **Toxicity pause is side-specific — opposite side always keeps quoting.**
8. **All monetary values use `decimal.Decimal` — never `float64`.**
9. **OFI exits `OFITracker.Normalized()` as `decimal.Decimal` — no `float64` enters price math.**
10. **EWMA volatility (`float64`) is used only for regime classification — never for price computation.**
11. **Stale feed (> 5s without update) trips the circuit breaker and cancels ALL orders including L9.**
12. **Position drift > `max_drift_threshold` for 3 consecutive reconciler cycles trips the circuit breaker.**
13. **Position reconciler does not auto-correct — human review required before restart.**
