# Spike Maker V2 — Upgrade Plan

**Date:** 2026-04-01
**Status:** PROPOSED
**Files Affected:**
- `internal/strategy/spike_depth_engine_v2.go`
- `internal/strategy/spike_maker_v2.go`

---

## 1. Problem Statement

The `spike-maker-v2` strategy **backs away too aggressively during price dumps**, resulting in zero inventory fills when the opportunity is richest. The root cause is a triple cascade:

1. **OFI tilt** shifts bid prices linearly toward zero — no floor prevents full withdrawal.
2. **Asymmetric Defense** cancels L1–L4 bids on volatility breach instead of sliding them deeper.
3. **Toxicity Cooldowns** trigger a full bid blackout — the bot sits out precisely when it should be accumulating inventory at discounted prices.

The fix is not to be braver — it is to be **smarter**: slide, don't flee. Maintain a presence at L5–L9 with reduced size, catch the dump, recover inventory gracefully.

---

## 2. State Analysis

### State 1: Normal (Low Volatility)

| Parameter | Behavior |
|-----------|----------|
| OFI | Near zero; symmetric quotes at L1–L3 |
| Spread | Base spread, no asymmetry |
| Toxicity | Clean; full size |
| Problem | None. Baseline is healthy. |

**No changes required in Normal state.**

---

### State 2: Spike (High Volatility / Price Drop)

| Parameter | Current (Broken) | Target (Fixed) |
|-----------|-----------------|----------------|
| OFI tilt | Linearly pushes bids to 0 (cancel) | Floors bid placement at L5 minimum |
| Asymmetric Defense | Cancels L1–L4; leaves nothing | Slides L1–L4 to L5–L9; halves size |
| Spread | Widens symmetrically | Widens asks more than bids (dump = buy opportunity) |
| Quote presence | Vanishes | Reduced size bids persist at L5–L9 |

**Core insight:** A dump is a *buying opportunity* for a market maker with zero initial inventory. Fleeing is a PnL mistake disguised as risk management.

---

### State 3: Captured (Adverse Selection / Toxic Fills)

| Parameter | Current (Broken) | Target (Fixed) |
|-----------|-----------------|----------------|
| Toxicity detection | Binary: toxic → full cooldown | Tiered: Mild/Moderate/Severe → graduated depth |
| Bid presence | Zero bids during cooldown | Minimum 10% size at L9 always maintained |
| Recovery | Hard timer → snap back to L1 | Gradual re-entry: L9 → L7 → L5 → L3 → L1 |
| Ask side | Also suppressed | Asks remain active at full size (sell the bounce) |

**Core insight:** Adverse selection during a dump is not the same as adverse selection during a pump. During a dump, being "captured" means *you are holding cheap inventory* — that is the goal.

---

## 3. Algorithmic Adjustments

### 3.1 OFI Tilt — Add Sticky Floor

**Current logic (broken):**
```go
// OFI linearly adjusts bid price. At high negative OFI, bids reach 0 (cancel).
bidPrice = midPrice - (baseSpread * 0.5) + (ofi * tiltMultiplier)
if bidPrice <= 0 {
    cancelAllBids()
}
```

**Fixed logic:**
```go
// OFI adjusts depth level, not absolute price. Bids slide deeper but never cancel.
func (e *SpikeMakerV2) computeBidDepth(ofi float64) DepthLevel {
    if ofi >= 0 {
        return L1 // Balanced or buy pressure — quote tight
    }
    // Map OFI intensity to depth level
    ofiAbs := math.Abs(ofi)
    switch {
    case ofiAbs < e.cfg.OFI.Tier1Threshold:
        return L2
    case ofiAbs < e.cfg.OFI.Tier2Threshold:
        return L3
    case ofiAbs < e.cfg.OFI.Tier3Threshold:
        return L5
    case ofiAbs < e.cfg.OFI.Tier4Threshold:
        return L7
    default:
        return L9 // Maximum depth — never cancel
    }
}
```

**Key change:** OFI now maps to *depth level*, not price nullification. The floor is L9 — bids always exist.

---

### 3.2 Asymmetric Defense — Slide, Don't Cancel

**Current logic (broken):**
```go
func (e *SpikeMakerV2) handleSpikeState(vol float64) {
    if vol > e.cfg.Defense.SpikeThreshold {
        e.cancelAllBids()                    // ← THE BUG
        e.widenAskSpread(vol * askMultiplier)
    }
}
```

**Fixed logic:**
```go
// DumpCatchConfig — new config struct
type DumpCatchConfig struct {
    // Triggers when price drops > DropPct within DropWindow
    DropPct         float64       // e.g. 0.015 = 1.5%
    DropWindow      time.Duration // e.g. 30s
    // Bid behavior during dump
    MinBidDepth     DepthLevel    // L5 — never shallower during dump
    MaxBidDepth     DepthLevel    // L9 — absolute floor
    SizeRatio       float64       // e.g. 0.40 = 40% of normal size
    // Graduated sizing across depth levels during dump
    DepthSizeWeights map[DepthLevel]float64 // L5:0.25, L6:0.25, L7:0.25, L8:0.15, L9:0.10
}

func (e *SpikeMakerV2) handleSpikeState(vol float64) {
    dumpDetected := e.detector.IsDump(e.cfg.DumpCatch.DropPct, e.cfg.DumpCatch.DropWindow)

    if dumpDetected {
        // SLIDE bids to L5–L9, do NOT cancel
        e.slideBidsToDepthRange(
            e.cfg.DumpCatch.MinBidDepth,
            e.cfg.DumpCatch.MaxBidDepth,
            e.cfg.DumpCatch.SizeRatio,
            e.cfg.DumpCatch.DepthSizeWeights,
        )
    } else if vol > e.cfg.Defense.SpikeThreshold {
        // Generic high-vol: slide to L3 minimum
        e.slideBidsToDepth(L3, 0.6)
    }

    // Asks: widen more aggressively — sell the bounce
    e.widenAskSpread(vol * e.cfg.Defense.AskMultiplier)
}

func (e *SpikeMakerV2) slideBidsToDepthRange(
    minDepth, maxDepth DepthLevel,
    totalSizeRatio float64,
    weights map[DepthLevel]float64,
) {
    e.cancelBidsShallowerThan(minDepth) // Cancel L1–L4 only
    for depth := minDepth; depth <= maxDepth; depth++ {
        w, ok := weights[depth]
        if !ok {
            continue
        }
        size := e.baseSize * totalSizeRatio * w
        price := e.depthEngine.PriceAtLevel(depth)
        e.placeBid(depth, price, size)
    }
}
```

---

### 3.3 Toxicity Cooldowns — Tiered, Never Full Blackout

**Current logic (broken):**
```go
func (e *SpikeMakerV2) onToxicFill(fill Fill) {
    e.toxicityScore += fill.Size * e.cfg.Toxicity.FillWeight
    if e.toxicityScore > e.cfg.Toxicity.Threshold {
        e.cancelAllBids()                  // ← THE BUG
        e.cooldownUntil = time.Now().Add(e.cfg.Toxicity.CooldownDuration)
    }
}
```

**Fixed logic:**
```go
// ToxicityTier — graduated response
type ToxicityTier int

const (
    TierClean    ToxicityTier = 0
    TierMild     ToxicityTier = 1  // score 0.3–0.5
    TierModerate ToxicityTier = 2  // score 0.5–0.75
    TierSevere   ToxicityTier = 3  // score > 0.75
    // NEVER a TierBlackout — full withdrawal is prohibited
)

type ToxicityConfig struct {
    // Score thresholds
    MildThreshold     float64 // 0.30
    ModerateThreshold float64 // 0.50
    SevereThreshold   float64 // 0.75

    // Response per tier: [depth, sizeRatio, cooldownWindow]
    MildResponse     TierResponse // {L5, 0.50, 10s}
    ModerateResponse TierResponse // {L7, 0.25, 20s}
    SevereResponse   TierResponse // {L9, 0.10, 30s}

    // Recovery: ramp back up in stages
    RecoveryStepInterval time.Duration // 15s between each level-up
    RecoveryStepDepth    int           // 2 levels shallower per step
    RecoverySizeStep     float64       // +0.15 size per step
}

func (e *SpikeMakerV2) getToxicityTier() ToxicityTier {
    score := e.toxicityScore
    switch {
    case score < e.cfg.Toxicity.MildThreshold:
        return TierClean
    case score < e.cfg.Toxicity.ModerateThreshold:
        return TierMild
    case score < e.cfg.Toxicity.SevereThreshold:
        return TierModerate
    default:
        return TierSevere
    }
}

func (e *SpikeMakerV2) applyToxicityResponse() {
    tier := e.getToxicityTier()
    var resp TierResponse
    switch tier {
    case TierClean:
        e.restoreNormalBids()
        return
    case TierMild:
        resp = e.cfg.Toxicity.MildResponse
    case TierModerate:
        resp = e.cfg.Toxicity.ModerateResponse
    case TierSevere:
        resp = e.cfg.Toxicity.SevereResponse
    }
    // Slide to response depth — NEVER cancel entirely
    e.slideBidsToDepth(resp.Depth, resp.SizeRatio)
    e.scheduleRecoveryStep(resp.CooldownWindow)
}

// Recovery: staircase back up, not a snap
func (e *SpikeMakerV2) onRecoveryTick() {
    currentDepth := e.currentBidDepth
    if currentDepth <= L1 {
        return // Already fully recovered
    }
    newDepth := DepthLevel(max(int(L1), int(currentDepth)-e.cfg.Toxicity.RecoveryStepDepth))
    newSize := min(1.0, e.currentSizeRatio + e.cfg.Toxicity.RecoverySizeStep)
    e.slideBidsToDepth(newDepth, newSize)
    e.scheduleRecoveryStep(e.cfg.Toxicity.RecoveryStepInterval)
}
```

---

## 4. New Config Parameters (`config.yaml`)

```yaml
spike_maker_v2:
  ofi_tilt:
    tier1_threshold: 0.15   # OFI → L2
    tier2_threshold: 0.30   # OFI → L3
    tier3_threshold: 0.50   # OFI → L5
    tier4_threshold: 0.70   # OFI → L7
    # >0.70 → L9 (floor)

  dump_catch:
    drop_pct: 0.015          # 1.5% drop triggers dump mode
    drop_window: 30s
    min_bid_depth: 5         # L5
    max_bid_depth: 9         # L9
    size_ratio: 0.40         # 40% of normal base size
    depth_size_weights:
      5: 0.25
      6: 0.25
      7: 0.25
      8: 0.15
      9: 0.10

  asymmetric_defense:
    spike_threshold: 0.008   # 0.8% vol triggers slide
    ask_multiplier: 2.5      # Asks widen 2.5x vol
    default_slide_depth: 3   # L3 for generic high-vol

  toxicity_cooldown:
    mild_threshold: 0.30
    moderate_threshold: 0.50
    severe_threshold: 0.75
    mild:
      depth: 5
      size_ratio: 0.50
      cooldown_window: 10s
    moderate:
      depth: 7
      size_ratio: 0.25
      cooldown_window: 20s
    severe:
      depth: 9
      size_ratio: 0.10
      cooldown_window: 30s
    recovery_step_interval: 15s
    recovery_step_depth: 2
    recovery_size_step: 0.15
```

---

## 5. spike_depth_engine_v2.go — Required Changes

### 5.1 Add `PriceAtLevel(depth DepthLevel) decimal.Decimal`

```go
// PriceAtLevel returns the absolute bid price for a given depth level
// relative to the current mid-price and tick size.
func (e *SpikeDepthEngineV2) PriceAtLevel(depth DepthLevel) decimal.Decimal {
    // Base spread at L1 is e.BaseSpread
    // Each level adds e.TickSize * e.LevelStep ticks
    offset := e.BaseSpread.Add(
        e.TickSize.Mul(decimal.NewFromInt(int64(depth - 1)).Mul(e.LevelStep)),
    )
    return e.MidPrice.Sub(offset)
}
```

### 5.2 Add `IsDump(dropPct float64, window time.Duration) bool`

```go
// IsDump returns true if price has fallen > dropPct within window.
func (e *SpikeDepthEngineV2) IsDump(dropPct float64, window time.Duration) bool {
    windowStart := time.Now().Add(-window)
    priceAtWindowStart := e.priceHistory.PriceAt(windowStart)
    if priceAtWindowStart.IsZero() {
        return false
    }
    drop := priceAtWindowStart.Sub(e.MidPrice).Div(priceAtWindowStart)
    return drop.InexactFloat64() >= dropPct
}
```

### 5.3 Expose `CancelBidsShallowerThan(depth DepthLevel)`

```go
func (e *SpikeDepthEngineV2) CancelBidsShallowerThan(depth DepthLevel) {
    for _, order := range e.activeBids {
        if order.Depth < depth {
            e.orderManager.Cancel(order.ID)
            delete(e.activeBids, order.ID)
        }
    }
}
```

---

## 6. spike_maker_v2.go — Required Changes

### 6.1 Remove `cancelAllBids()` calls (2 locations)

**Find and replace both occurrences:**

```go
// BEFORE (line ~142):
e.cancelAllBids()

// AFTER:
e.slideBidsToDepth(e.cfg.DumpCatch.MinBidDepth, e.cfg.DumpCatch.SizeRatio)
```

```go
// BEFORE (line ~198, toxicity handler):
e.cancelAllBids()
e.cooldownUntil = time.Now().Add(e.cfg.Toxicity.CooldownDuration)

// AFTER:
e.applyToxicityResponse()
```

### 6.2 Add `slideBidsToDepthRange()` method

See Section 3.2 above — implement as written.

### 6.3 Add `applyToxicityResponse()` and `onRecoveryTick()`

See Section 3.3 above — implement as written.

### 6.4 Replace hardcoded OFI logic in `quoteUpdate()`

```go
// BEFORE:
bidPrice := midPrice.Sub(baseSpread.Mul(decimal.NewFromFloat(0.5))).
    Add(decimal.NewFromFloat(ofi * tiltMultiplier))
if bidPrice.LessThanOrEqual(decimal.Zero) {
    e.cancelAllBids()
    return
}

// AFTER:
bidDepth := e.computeBidDepth(ofi)
bidPrice := e.depthEngine.PriceAtLevel(bidDepth)
e.slideBidsToDepth(bidDepth, e.currentSizeRatio)
```

---

## 7. Testing Checklist

- [ ] **Normal state:** Bids at L1–L2, symmetric, full size. No regression.
- [ ] **Spike state (1.5% drop in 30s):** Bids slide to L5–L9. Size reduces to 40%. No cancels.
- [ ] **High OFI (> 0.70):** Bids floor at L9. Never zero.
- [ ] **Mild toxicity (score 0.3–0.5):** Bids slide to L5, 50% size. Recovery starts after 10s.
- [ ] **Severe toxicity (score > 0.75):** Bids at L9, 10% size. Recovery ladder executes every 15s.
- [ ] **Recovery:** Staircase from L9 → L7 → L5 → L3 → L1 over ~60s. No snap.
- [ ] **Backtest:** On historical dump events, measure fill rate at L5–L9 vs. old zero-fill behavior.

---

## 8. Risk Considerations

| Risk | Mitigation |
|------|-----------|
| Holding inventory through a sustained dump | Hard stop-loss per position at `MaxInventoryLoss`; L9 bids are tiny (10% size) |
| L9 bids filled by informed flow | Toxicity score accounts for this; tier escalates depth automatically |
| Recovery too fast, re-entering toxic flow | Conservative `RecoveryStepInterval: 15s`; toxicity score decays slowly |
| Config tuning difficulty | All thresholds externalized to `config.yaml`; paper trade before live deploy |

---

## 9. Summary

The core change is a **philosophy shift**: from *cancel-on-risk* to *slide-on-risk*. The bot always maintains a bid presence — at progressively deeper levels as risk rises. This converts the "backing away too fast" failure into a controlled depth-sliding behavior that catches inventory during dumps at L5–L9, exactly where the margin is highest.

**Three rules:**
1. OFI → depth level, not price nullification.
2. Defense → slide bids, don't cancel them.
3. Toxicity → tier the response, never blackout.
