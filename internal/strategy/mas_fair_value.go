package strategy

import (
	"math"
	"sync"

	"github.com/shopspring/decimal"
)

// ComputeMicroPrice returns the quantity-weighted mid-price.
// Formula: (bestAsk*bidQty + bestBid*askQty) / (bidQty + askQty)
// Falls back to arithmetic mid when total qty is zero.
func ComputeMicroPrice(bestBid, bestAsk, bidQty, askQty decimal.Decimal) decimal.Decimal {
	totalQty := bidQty.Add(askQty)
	if totalQty.IsZero() {
		return bestBid.Add(bestAsk).Div(decimal.NewFromInt(2))
	}
	return bestAsk.Mul(bidQty).Add(bestBid.Mul(askQty)).Div(totalQty)
}

// OFITracker accumulates order-flow imbalance from the trade tape.
// Internal float64 for performance; decimal.Decimal only at the public boundary.
// No float64 OFI value may escape this struct into price math.
type OFITracker struct {
	mu         sync.Mutex
	cumulative float64
	runningMax float64
}

const ofiFloor = 1e-6

// Update records a signed delta. isBid=true adds positive flow; false subtracts.
// delta must be the trade quantity as decimal.Decimal; converted to float64 here only.
func (t *OFITracker) Update(isBid bool, delta decimal.Decimal) {
	qty, _ := delta.Float64()
	t.mu.Lock()
	defer t.mu.Unlock()
	if isBid {
		t.cumulative += qty
	} else {
		t.cumulative -= qty
	}
	if abs := math.Abs(t.cumulative); abs > t.runningMax {
		t.runningMax = abs
	}
}

// Normalized returns OFI in [-1, +1] as decimal.Decimal.
// This is the ONLY exit point for OFI. All callers must accept decimal.Decimal.
func (t *OFITracker) Normalized() decimal.Decimal {
	t.mu.Lock()
	defer t.mu.Unlock()
	denom := t.runningMax
	if denom < ofiFloor {
		denom = ofiFloor
	}
	norm := t.cumulative / denom
	if norm > 1.0 {
		norm = 1.0
	} else if norm < -1.0 {
		norm = -1.0
	}
	return decimal.NewFromFloat(norm)
}

// Reset clears accumulated state. Call at session start.
func (t *OFITracker) Reset() {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.cumulative = 0
	t.runningMax = 0
}

// ComputeFairValue blends micro-price with the OFI adjustment.
// Formula: fair_value = micro_price + ofi_normalized * ofi_alpha * tick_size
func ComputeFairValue(microPrice, ofiNorm decimal.Decimal, cfg FairValueConfig) decimal.Decimal {
	adjustment := ofiNorm.Mul(cfg.OFIAlpha).Mul(cfg.TickSize)
	return microPrice.Add(adjustment)
}
