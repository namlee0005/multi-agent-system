package strategy

import (
	"sync"
	"time"

	"github.com/shopspring/decimal"
)

// PriceSnapshot is a single timestamped mid-price observation used for
// post-fill adverse-move detection.
type PriceSnapshot struct {
	Mid       decimal.Decimal
	Timestamp time.Time
}

// PriceHistory is a ring buffer of recent price snapshots. The toxicity
// evaluator scans this to detect adverse moves within the detection window.
type PriceHistory struct {
	mu   sync.Mutex
	buf  []PriceSnapshot
	head int
	full bool
}

// NewPriceHistory allocates a ring buffer of the given capacity.
func NewPriceHistory(capacity int) *PriceHistory {
	if capacity <= 0 {
		capacity = 1024
	}
	return &PriceHistory{buf: make([]PriceSnapshot, capacity)}
}

// Add appends a price snapshot to the ring buffer.
func (h *PriceHistory) Add(snap PriceSnapshot) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.buf[h.head] = snap
	h.head = (h.head + 1) % len(h.buf)
	if h.head == 0 {
		h.full = true
	}
}

// Since returns all snapshots with Timestamp >= cutoff, ordered oldest first.
func (h *PriceHistory) Since(cutoff time.Time) []PriceSnapshot {
	h.mu.Lock()
	defer h.mu.Unlock()

	var result []PriceSnapshot
	n := len(h.buf)
	count := n
	if !h.full {
		count = h.head
	}
	start := 0
	if h.full {
		start = h.head
	}
	for i := 0; i < count; i++ {
		idx := (start + i) % n
		if !h.buf[idx].Timestamp.Before(cutoff) {
			result = append(result, h.buf[idx])
		}
	}
	return result
}

// EvaluateFill checks whether the market moved adversely against a fill within
// the detection window.
//
// IMPORTANT: This must be called AFTER the detection window has elapsed, not at
// fill time. The caller (Tick) defers evaluation until now >= fill.Timestamp + window,
// ensuring price history contains post-fill snapshots to evaluate against.
//
// "Adverse" means:
//   - We bought (Bid fill) and price dropped by >= toxicMoveTicks * tickSize
//   - We sold  (Ask fill) and price rose   by >= toxicMoveTicks * tickSize
func EvaluateFill(fill Fill, history *PriceHistory, regime VolatilityRegime, cfg ToxicityConfig, tickSize decimal.Decimal) bool {
	window := cfg.ToxicDetectionWindow
	if regime == RegimeSpike {
		window = cfg.SpikeDetectionWindow
	}

	cutoff := fill.Timestamp
	deadline := fill.Timestamp.Add(window)
	snapshots := history.Since(cutoff)

	threshold := tickSize.Mul(decimal.NewFromInt(int64(cfg.ToxicMoveTicks)))

	for _, snap := range snapshots {
		if snap.Timestamp.After(deadline) {
			break
		}
		switch fill.Side {
		case Bid:
			if fill.Price.Sub(snap.Mid).GreaterThanOrEqual(threshold) {
				return true
			}
		case Ask:
			if snap.Mid.Sub(fill.Price).GreaterThanOrEqual(threshold) {
				return true
			}
		}
	}
	return false
}

// pauseTiers maps rolling toxic fill counts to pause durations.
// 0 toxic fills = 0s, 1-2 = 15s, 3-5 = 45s, 6+ = 120s.
var pauseTiers = []struct {
	minCount int
	duration time.Duration
}{
	{6, 120 * time.Second},
	{3, 45 * time.Second},
	{1, 15 * time.Second},
}

func tierDuration(count int) time.Duration {
	for _, t := range pauseTiers {
		if count >= t.minCount {
			return t.duration
		}
	}
	return 0
}

// ToxicityPauseManager tracks toxic fills per side and manages tiered pauses.
// L9 compliance anchors remain active during a toxicity pause -- only the
// circuit breaker cancels L9.
//
// All methods accept an explicit `now time.Time` parameter instead of calling
// time.Now(), making the manager deterministic for backtesting.
type ToxicityPauseManager struct {
	mu sync.Mutex

	bidToxicCount int
	askToxicCount int

	bidPauseUntil time.Time
	askPauseUntil time.Time
}

// RecordFill registers a toxic fill and returns the pause duration applied.
// If isToxic is false, returns 0 with no side effects.
// `now` is the current tick time (not time.Now()), ensuring backtest determinism.
func (m *ToxicityPauseManager) RecordFill(side Side, isToxic bool, now time.Time) time.Duration {
	if !isToxic {
		return 0
	}

	m.mu.Lock()
	defer m.mu.Unlock()

	switch side {
	case Bid:
		m.bidToxicCount++
		d := tierDuration(m.bidToxicCount)
		m.bidPauseUntil = now.Add(d)
		return d
	case Ask:
		m.askToxicCount++
		d := tierDuration(m.askToxicCount)
		m.askPauseUntil = now.Add(d)
		return d
	}
	return 0
}

// IsPaused returns true if the given side is under a toxicity pause at time `now`.
func (m *ToxicityPauseManager) IsPaused(side Side, now time.Time) bool {
	m.mu.Lock()
	defer m.mu.Unlock()

	switch side {
	case Bid:
		return now.Before(m.bidPauseUntil)
	case Ask:
		return now.Before(m.askPauseUntil)
	}
	return false
}

// PausedSide returns the currently paused side at time `now`, or nil if neither.
func (m *ToxicityPauseManager) PausedSide(now time.Time) *Side {
	m.mu.Lock()
	defer m.mu.Unlock()

	bidPaused := now.Before(m.bidPauseUntil)
	askPaused := now.Before(m.askPauseUntil)

	if bidPaused {
		s := Bid
		return &s
	}
	if askPaused {
		s := Ask
		return &s
	}
	return nil
}

// Reset clears all toxic fill counts and pauses. Call at session start.
func (m *ToxicityPauseManager) Reset() {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.bidToxicCount = 0
	m.askToxicCount = 0
	m.bidPauseUntil = time.Time{}
	m.askPauseUntil = time.Time{}
}

// Counts returns the current rolling toxic fill counts (bid, ask) for logging.
func (m *ToxicityPauseManager) Counts() (int, int) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.bidToxicCount, m.askToxicCount
}
