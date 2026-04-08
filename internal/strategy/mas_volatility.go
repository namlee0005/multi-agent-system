package strategy

import (
	"math"
	"sync"
)

// ---------------------------------------------------------------------------
// 3.1 EWMA Volatility Tracker
// ---------------------------------------------------------------------------

// VolatilityTracker computes realized volatility via an EWMA of squared
// log-returns.  It is safe for concurrent use.
//
// λ (lambda) is derived from ewma_halflife_seconds:
//
//	λ = exp(-ln(2) / halflife_seconds)
//
// Default halflife of 15 s gives λ ≈ 0.955, meaning a flash-crash spike
// registers within ~30 s (2× halflife) vs. 60 s for a 60 s rolling window.
type VolatilityTracker struct {
	mu       sync.Mutex
	lambda   float64
	ewmaVar  float64
	prevMid  float64
	seeded   bool
}

// NewVolatilityTracker creates a tracker with the given halflife in seconds.
// Pass cfg.Volatility.EWMAHalflifeSeconds (default 15).
func NewVolatilityTracker(halflifeSeconds float64) *VolatilityTracker {
	if halflifeSeconds <= 0 {
		halflifeSeconds = 15
	}
	lambda := math.Exp(-math.Log(2) / halflifeSeconds)
	return &VolatilityTracker{lambda: lambda}
}

// Update ingests a new mid-price observation, computes the log-return, and
// advances the EWMA variance.
//
//	ewma_var = λ × prev_ewma_var + (1-λ) × log_return²
//
// The first call seeds prevMid without updating ewmaVar (no log-return yet).
func (v *VolatilityTracker) Update(midPrice float64) {
	if midPrice <= 0 {
		return
	}
	v.mu.Lock()
	defer v.mu.Unlock()

	if !v.seeded {
		v.prevMid = midPrice
		v.seeded = true
		return
	}

	logReturn := math.Log(midPrice / v.prevMid)
	v.ewmaVar = v.lambda*v.ewmaVar + (1-v.lambda)*logReturn*logReturn
	v.prevMid = midPrice
}

// EWMAVol returns the current annualized (in tick-time) realized volatility
// estimate as sqrt(ewma_var).  Returns 0 before the second Update call.
func (v *VolatilityTracker) EWMAVol() float64 {
	v.mu.Lock()
	defer v.mu.Unlock()
	return math.Sqrt(v.ewmaVar)
}

// EWMAVar returns the raw variance for direct access (used by MASState).
func (v *VolatilityTracker) EWMAVar() float64 {
	v.mu.Lock()
	defer v.mu.Unlock()
	return v.ewmaVar
}

// Reset clears state (call at session start).
func (v *VolatilityTracker) Reset() {
	v.mu.Lock()
	defer v.mu.Unlock()
	v.ewmaVar = 0
	v.prevMid = 0
	v.seeded = false
}

// ---------------------------------------------------------------------------
// 3.2 Regime FSM
// ---------------------------------------------------------------------------

// ClassifyRegime applies hysteresis to prevent regime thrashing at the
// vol_threshold boundary.
//
//   - Enter Spike  when vol ≥ cfg.VolThreshold        (from Sideways)
//   - Exit  Spike  when vol <  cfg.VolExitThreshold   (back to Sideways)
//
// VolExitThreshold must be < VolThreshold (typically 80% of threshold).
// Caller owns locking if current is read from shared state.
func ClassifyRegime(vol float64, current VolatilityRegime, cfg VolatilityConfig) VolatilityRegime {
	switch current {
	case RegimeSideways:
		if vol >= cfg.VolThreshold {
			return RegimeSpike
		}
		return RegimeSideways
	case RegimeSpike:
		if vol < cfg.VolExitThreshold {
			return RegimeSideways
		}
		return RegimeSpike
	default:
		return RegimeSideways
	}
}
