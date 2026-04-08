package strategy

import (
	"log/slog"
	"sync"
	"time"

	"github.com/shopspring/decimal"
)

// QuoteConfig holds parameters for quote generation across regimes.
// Passed alongside MASConfig during Init; not hot-reloaded.
type QuoteConfig struct {
	BaseSpread           decimal.Decimal `yaml:"base_spread"`
	BaseSize             decimal.Decimal `yaml:"base_size"`
	SpikeNearSpreadMul   decimal.Decimal `yaml:"spike_near_spread_multiplier"`
	SpikeNearSizeRatio   decimal.Decimal `yaml:"spike_near_size_ratio"`
	SpikeDeepOffsetTicks int             `yaml:"spike_deep_offset_ticks"`
	SpikeDeepSizeRatio   decimal.Decimal `yaml:"spike_deep_size_ratio"`
	ComplianceFatTailPct decimal.Decimal `yaml:"compliance_fat_tail_pct"`
}

// TickOutput is returned by Tick to the execution layer.
type TickOutput struct {
	Orders     []Order
	CancelBids bool
	CancelAsks bool
	CancelAll  bool
	State      MASState
}

// Strategy is the interface the execution layer calls each tick.
type Strategy interface {
	Name() string
	Init(cfg *MASConfig, quoteCfg *QuoteConfig) error
	Tick(book OrderBook, trades []TradeEvent, now time.Time) TickOutput
	OnFill(fill Fill)
	OnOrderUpdate(orderID string, status string)
	UpdateConfig(cfg *MASConfig)
}

// deferredFill is a fill awaiting toxicity evaluation. Evaluation is deferred
// until the detection window has elapsed so that post-fill price snapshots
// exist in PriceHistory for the evaluator to scan.
type deferredFill struct {
	fill     Fill
	regime   VolatilityRegime
	deadline time.Time
}

// MASStrategy is the capital-preservation market-making strategy.
//
// Concurrency contract:
//   - Tick() is called from a single goroutine (the tick loop).
//   - OnFill() may be called from the exchange adapter goroutine.
//   - fillMu protects pendingFills, which is the ONLY shared state between
//     OnFill and Tick. All other fields are owned exclusively by Tick.
type MASStrategy struct {
	// fillMu guards pendingFills only. OnFill appends; Tick drains.
	fillMu       sync.Mutex
	pendingFills []Fill

	// Everything below is single-goroutine (Tick pipeline only).
	state        MASState
	ofi          OFITracker
	vol          *VolatilityTracker
	toxicity     ToxicityPauseManager
	priceHist    *PriceHistory
	quoteCfg     QuoteConfig
	logger       *slog.Logger
	awaitingEval []deferredFill
}

// Compile-time interface check.
var _ Strategy = (*MASStrategy)(nil)

// NewMASStrategy constructs the strategy. Call Init before first Tick.
func NewMASStrategy(logger *slog.Logger) *MASStrategy {
	if logger == nil {
		logger = slog.Default()
	}
	return &MASStrategy{logger: logger}
}

func (s *MASStrategy) Name() string { return "MAS-CapitalPreservation" }

// Init wires config, creates sub-components, resets state.
func (s *MASStrategy) Init(cfg *MASConfig, quoteCfg *QuoteConfig) error {
	MASConfigPtr.Store(cfg)
	s.quoteCfg = *quoteCfg
	s.vol = NewVolatilityTracker(cfg.Volatility.EWMAHalflifeSeconds)
	s.priceHist = NewPriceHistory(4096)
	s.ofi.Reset()
	s.toxicity.Reset()
	s.pendingFills = nil
	s.awaitingEval = nil
	s.state = MASState{
		Regime:           RegimeSideways,
		LastFeedTimestamp: time.Time{},
	}
	return nil
}

// Tick runs the full pipeline: drain fills -> fair value -> regime -> quotes -> caps.
func (s *MASStrategy) Tick(book OrderBook, trades []TradeEvent, now time.Time) TickOutput {
	cfg := MASConfigPtr.Load()
	if cfg == nil {
		return TickOutput{CancelAll: true}
	}

	s.state.LastFeedTimestamp = now

	// --- 0. Drain pending fills (mutex-protected handoff from OnFill) ---
	s.drainFills(cfg, now)

	// --- 1. Evaluate deferred toxicity for fills whose window has elapsed ---
	s.evaluateDeferredFills(cfg, now)

	// --- 2. Ingest trades into OFI accumulator ---
	for _, t := range trades {
		s.ofi.Update(t.Side == Bid, t.Qty)
	}

	// --- 3. Compute fair value: micro-price + OFI adjustment ---
	microPrice := ComputeMicroPrice(book.BestBid, book.BestAsk, book.BidQty, book.AskQty)
	ofiNorm := s.ofi.Normalized()
	fairValue := ComputeFairValue(microPrice, ofiNorm, cfg.FairValue)

	s.state.FairValue = fairValue
	s.state.OFINormalized = ofiNorm

	// Record mid-price for toxicity lookback.
	midPrice := book.BestBid.Add(book.BestAsk).Div(decimal.NewFromInt(2))
	s.priceHist.Add(PriceSnapshot{Mid: midPrice, Timestamp: now})

	// --- 4. Update EWMA volatility and classify regime ---
	midF, _ := midPrice.Float64()
	s.vol.Update(midF)
	ewmaVol := s.vol.EWMAVol()
	s.state.EWMAVol = ewmaVol
	s.state.EWMAVar = s.vol.EWMAVar()
	s.state.Regime = ClassifyRegime(ewmaVol, s.state.Regime, cfg.Volatility)

	// --- 5. Inventory ratio for skew ---
	s.state.InventoryRatio = ComputeInventoryRatio(s.state.NetPosition, cfg.Inventory)

	// --- 6. Generate L0-L9 quotes based on regime ---
	var orders []Order
	switch s.state.Regime {
	case RegimeSideways:
		orders = s.buildSidewaysQuotes(fairValue)
	case RegimeSpike:
		orders = s.buildSpikeQuotes(fairValue, cfg)
	}

	// --- 7. Apply inventory skew to all orders ---
	orders = ApplyInventorySkew(orders, s.state.InventoryRatio, cfg.Inventory, cfg.FairValue.TickSize)

	// --- 8. Compliance fat-tail: force L9 to exactly 1.95% from mid ---
	orders = s.applyComplianceFatTail(orders, midPrice)

	// --- 9. Toxicity pauses: remove paused side except L9 anchor ---
	bidPaused := s.toxicity.IsPaused(Bid, now)
	askPaused := s.toxicity.IsPaused(Ask, now)
	if bidPaused {
		orders = filterPausedSide(orders, Bid)
		side := Bid
		s.state.ToxicPausedSide = &side
	} else if askPaused {
		orders = filterPausedSide(orders, Ask)
		side := Ask
		s.state.ToxicPausedSide = &side
	} else {
		s.state.ToxicPausedSide = nil
	}

	// --- 10. Emergency hard caps: removes ALL including L9 ---
	cancelBids, cancelAsks := CheckEmergencyCap(s.state.NetPosition, cfg.Inventory)
	if cancelBids {
		orders = removeSide(orders, Bid)
	}
	if cancelAsks {
		orders = removeSide(orders, Ask)
	}

	bidToxic, askToxic := s.toxicity.Counts()
	s.state.ToxicFillCount = bidToxic + askToxic

	s.logger.Info("tick",
		"regime", s.state.Regime.String(),
		"fair_value", fairValue.String(),
		"ewma_vol", ewmaVol,
		"inventory_ratio", s.state.InventoryRatio,
		"orders", len(orders),
		"cancel_bids", cancelBids,
		"cancel_asks", cancelAsks,
		"bid_paused", bidPaused,
		"ask_paused", askPaused,
		"pending_eval", len(s.awaitingEval),
	)

	return TickOutput{
		Orders:     orders,
		CancelBids: cancelBids,
		CancelAsks: cancelAsks,
		State:      s.state,
	}
}

// drainFills atomically moves fills from the pending queue (written by OnFill)
// into the Tick goroutine. Updates NetPosition and queues each fill for
// deferred toxicity evaluation.
func (s *MASStrategy) drainFills(cfg *MASConfig, now time.Time) {
	s.fillMu.Lock()
	fills := s.pendingFills
	s.pendingFills = nil
	s.fillMu.Unlock()

	for _, fill := range fills {
		// Update net position (now safe: single goroutine).
		if fill.Side == Bid {
			s.state.NetPosition = s.state.NetPosition.Add(fill.Qty)
		} else {
			s.state.NetPosition = s.state.NetPosition.Sub(fill.Qty)
		}

		// Compute the detection window deadline for deferred evaluation.
		window := cfg.Toxicity.ToxicDetectionWindow
		if s.state.Regime == RegimeSpike {
			window = cfg.Toxicity.SpikeDetectionWindow
		}

		s.awaitingEval = append(s.awaitingEval, deferredFill{
			fill:     fill,
			regime:   s.state.Regime,
			deadline: fill.Timestamp.Add(window),
		})
	}
}

// evaluateDeferredFills checks fills whose detection window has elapsed.
// By this point PriceHistory contains post-fill snapshots, so EvaluateFill
// can actually detect adverse price moves.
func (s *MASStrategy) evaluateDeferredFills(cfg *MASConfig, now time.Time) {
	remaining := s.awaitingEval[:0] // reuse backing array
	for _, df := range s.awaitingEval {
		if now.Before(df.deadline) {
			remaining = append(remaining, df)
			continue
		}
		// Window elapsed: evaluate toxicity with actual post-fill price data.
		isToxic := EvaluateFill(df.fill, s.priceHist, df.regime, cfg.Toxicity, cfg.FairValue.TickSize)
		pauseDur := s.toxicity.RecordFill(df.fill.Side, isToxic, now)

		if isToxic {
			s.logger.Warn("toxic fill detected",
				"side", df.fill.Side,
				"price", df.fill.Price.String(),
				"qty", df.fill.Qty.String(),
				"pause_duration", pauseDur.String(),
				"order_id", df.fill.OrderID,
				"fill_time", df.fill.Timestamp.String(),
				"eval_time", now.String(),
			)
		}
	}
	s.awaitingEval = remaining
}

// buildSidewaysQuotes generates L0-L9 bid+ask with uniform spread and size.
func (s *MASStrategy) buildSidewaysQuotes(fairValue decimal.Decimal) []Order {
	qcfg := s.quoteCfg
	orders := make([]Order, 0, 20)

	for lvl := L0; lvl <= L9; lvl++ {
		bidPrice := PriceAtLevel(Bid, lvl, fairValue, qcfg.BaseSpread)
		askPrice := PriceAtLevel(Ask, lvl, fairValue, qcfg.BaseSpread)
		orders = append(orders,
			Order{Side: Bid, Level: lvl, Price: bidPrice, Size: qcfg.BaseSize},
			Order{Side: Ask, Level: lvl, Price: askPrice, Size: qcfg.BaseSize},
		)
	}
	return orders
}

// buildSpikeQuotes generates regime-aware quotes:
//   - L0-L3: widened spread (thin size) to avoid fills near fair value
//   - L4:    empty buffer zone with no orders
//   - L5-L9: deep offset (thick size) for capital preservation
func (s *MASStrategy) buildSpikeQuotes(fairValue decimal.Decimal, cfg *MASConfig) []Order {
	qcfg := s.quoteCfg
	orders := make([]Order, 0, 18)

	nearSpread := qcfg.BaseSpread.Mul(qcfg.SpikeNearSpreadMul)
	nearSize := qcfg.BaseSize.Mul(qcfg.SpikeNearSizeRatio)

	for lvl := L0; lvl <= L3; lvl++ {
		bidPrice := PriceAtLevel(Bid, lvl, fairValue, nearSpread)
		askPrice := PriceAtLevel(Ask, lvl, fairValue, nearSpread)
		orders = append(orders,
			Order{Side: Bid, Level: lvl, Price: bidPrice, Size: nearSize},
			Order{Side: Ask, Level: lvl, Price: askPrice, Size: nearSize},
		)
	}

	// L4: intentionally empty buffer zone.

	nearEdge := nearSpread.Mul(decimal.NewFromInt(4))
	deepStep := cfg.FairValue.TickSize.Mul(decimal.NewFromInt(int64(qcfg.SpikeDeepOffsetTicks)))
	deepSize := qcfg.BaseSize.Mul(qcfg.SpikeDeepSizeRatio)

	for lvl := L5; lvl <= L9; lvl++ {
		rank := decimal.NewFromInt(int64(lvl - L5 + 1))
		totalOffset := nearEdge.Add(deepStep.Mul(rank))
		bidPrice := fairValue.Sub(totalOffset)
		askPrice := fairValue.Add(totalOffset)
		orders = append(orders,
			Order{Side: Bid, Level: lvl, Price: bidPrice, Size: deepSize},
			Order{Side: Ask, Level: lvl, Price: askPrice, Size: deepSize},
		)
	}

	return orders
}

// applyComplianceFatTail overrides L9 bid/ask to sit exactly at
// ComplianceFatTailPct (default 1.95%) from mid-price.
// L9 survives toxicity pauses. Only circuit breaker or emergency cap removes it.
func (s *MASStrategy) applyComplianceFatTail(orders []Order, midPrice decimal.Decimal) []Order {
	pct := s.quoteCfg.ComplianceFatTailPct
	if pct.IsZero() {
		pct = decimal.NewFromFloat(0.0195)
	}

	offset := midPrice.Mul(pct)
	l9Bid := midPrice.Sub(offset)
	l9Ask := midPrice.Add(offset)

	foundBid, foundAsk := false, false
	for i := range orders {
		if orders[i].Level != L9 {
			continue
		}
		if orders[i].Side == Bid {
			orders[i].Price = l9Bid
			foundBid = true
		} else {
			orders[i].Price = l9Ask
			foundAsk = true
		}
	}

	if !foundBid {
		orders = append(orders, Order{Side: Bid, Level: L9, Price: l9Bid, Size: s.quoteCfg.BaseSize})
	}
	if !foundAsk {
		orders = append(orders, Order{Side: Ask, Level: L9, Price: l9Ask, Size: s.quoteCfg.BaseSize})
	}

	return orders
}

// filterPausedSide removes orders for a paused side but keeps L9 (compliance anchor).
func filterPausedSide(orders []Order, pausedSide Side) []Order {
	result := make([]Order, 0, len(orders))
	for _, o := range orders {
		if o.Side == pausedSide && o.Level != L9 {
			continue
		}
		result = append(result, o)
	}
	return result
}

// removeSide strips ALL orders for a side including L9 (emergency cap override).
func removeSide(orders []Order, side Side) []Order {
	result := make([]Order, 0, len(orders))
	for _, o := range orders {
		if o.Side != side {
			result = append(result, o)
		}
	}
	return result
}

// OnFill queues a fill for processing in the next Tick. This is the only method
// safe to call from a different goroutine (the exchange adapter). The fill is
// appended to pendingFills under fillMu; Tick drains it at pipeline entry.
func (s *MASStrategy) OnFill(fill Fill) {
	s.fillMu.Lock()
	s.pendingFills = append(s.pendingFills, fill)
	s.fillMu.Unlock()
}

// OnOrderUpdate handles order lifecycle events. Currently a no-op placeholder.
func (s *MASStrategy) OnOrderUpdate(orderID string, status string) {
	// Order lifecycle tracking (ack, partial, cancelled) would go here.
}

// UpdateConfig hot-swaps the config pointer. Re-creates the volatility tracker
// if the halflife changed.
func (s *MASStrategy) UpdateConfig(cfg *MASConfig) {
	prev := MASConfigPtr.Load()
	MASConfigPtr.Store(cfg)

	if prev == nil || prev.Volatility.EWMAHalflifeSeconds != cfg.Volatility.EWMAHalflifeSeconds {
		s.vol = NewVolatilityTracker(cfg.Volatility.EWMAHalflifeSeconds)
	}
}
