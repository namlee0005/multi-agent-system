package strategy

import (
	"testing"
	"time"

	"github.com/shopspring/decimal"
)

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

func d(v string) decimal.Decimal { return decimal.RequireFromString(v) }

func testConfig() *MASConfig {
	return &MASConfig{
		FairValue: FairValueConfig{
			OFIAlpha: d("0.5"),
			TickSize: d("0.01"),
		},
		Volatility: VolatilityConfig{
			EWMAHalflifeSeconds: 15,
			VolThreshold:        0.05,
			VolExitThreshold:    0.04,
			UseEWMA:             true,
		},
		Inventory: InventoryConfig{
			MaxInventory: d("100"),
			EmergencyCap: d("200"),
			MaxSkewTicks: 5,
		},
		Toxicity: ToxicityConfig{
			ToxicMoveTicks:       3,
			ToxicDetectionWindow: 5 * time.Second,
			SpikeDetectionWindow: 10 * time.Second,
		},
		CircuitBreaker: CircuitBreakerConfig{
			MaxLossPerSession: d("1000"),
			StaleFeedTimeout:  30 * time.Second,
		},
		Reconciler: ReconcilerConfig{
			PollInterval:       5 * time.Second,
			MaxDriftThreshold:  d("10"),
			MaxConsecutiveMiss: 3,
		},
	}
}

func testQuoteConfig() *QuoteConfig {
	return &QuoteConfig{
		BaseSpread:           d("0.05"),
		BaseSize:             d("10"),
		SpikeNearSpreadMul:   d("4"),
		SpikeNearSizeRatio:   d("0.25"),
		SpikeDeepOffsetTicks: 20,
		SpikeDeepSizeRatio:   d("2"),
		ComplianceFatTailPct: d("0.0195"),
	}
}

func balancedBook() OrderBook {
	return OrderBook{
		BestBid:   d("100.00"),
		BestAsk:   d("100.10"),
		BidQty:    d("50"),
		AskQty:    d("50"),
		Timestamp: time.Now(),
	}
}

func initStrategy(t *testing.T) *MASStrategy {
	t.Helper()
	s := NewMASStrategy(nil)
	if err := s.Init(testConfig(), testQuoteConfig()); err != nil {
		t.Fatalf("Init failed: %v", err)
	}
	return s
}

func countSide(orders []Order, side Side) int {
	n := 0
	for _, o := range orders {
		if o.Side == side {
			n++
		}
	}
	return n
}

func findLevel(orders []Order, side Side, level DepthLevel) *Order {
	for i := range orders {
		if orders[i].Side == side && orders[i].Level == level {
			return &orders[i]
		}
	}
	return nil
}

// ---------------------------------------------------------------------------
// Unit tests: ComputeMicroPrice
// ---------------------------------------------------------------------------

func TestComputeMicroPrice_Balanced(t *testing.T) {
	mid := ComputeMicroPrice(d("100"), d("101"), d("50"), d("50"))
	expected := d("100.5")
	if !mid.Equal(expected) {
		t.Errorf("balanced micro-price = %s, want %s", mid, expected)
	}
}

func TestComputeMicroPrice_Imbalanced(t *testing.T) {
	mid := ComputeMicroPrice(d("100"), d("101"), d("90"), d("10"))
	arithMid := d("100.5")
	if !mid.GreaterThan(arithMid) {
		t.Errorf("bid-heavy micro-price %s should exceed arithmetic mid %s", mid, arithMid)
	}
}

func TestComputeMicroPrice_ZeroQty(t *testing.T) {
	mid := ComputeMicroPrice(d("100"), d("101"), d("0"), d("0"))
	expected := d("100.5")
	if !mid.Equal(expected) {
		t.Errorf("zero-qty fallback = %s, want %s", mid, expected)
	}
}

// ---------------------------------------------------------------------------
// Unit tests: OFITracker
// ---------------------------------------------------------------------------

func TestOFITracker_BuyHeavy_Positive(t *testing.T) {
	var ofi OFITracker
	ofi.Update(true, d("10"))
	ofi.Update(true, d("10"))
	ofi.Update(false, d("2"))

	norm := ofi.Normalized()
	if !norm.GreaterThan(decimal.Zero) {
		t.Errorf("buy-heavy OFI should be positive, got %s", norm)
	}
}

func TestOFITracker_SellHeavy_Negative(t *testing.T) {
	var ofi OFITracker
	ofi.Update(false, d("10"))
	ofi.Update(false, d("10"))

	norm := ofi.Normalized()
	if !norm.LessThan(decimal.Zero) {
		t.Errorf("sell-heavy OFI should be negative, got %s", norm)
	}
}

func TestOFITracker_FirstTick_NoPanic(t *testing.T) {
	var ofi OFITracker
	norm := ofi.Normalized()
	if norm.Abs().GreaterThan(d("1")) {
		t.Errorf("first-tick normalization = %s, want within [-1,1]", norm)
	}
}

// ---------------------------------------------------------------------------
// Unit tests: VolatilityTracker + ClassifyRegime
// ---------------------------------------------------------------------------

func TestVolatilityTracker_FlatPrices_NearZero(t *testing.T) {
	vt := NewVolatilityTracker(15)
	for i := 0; i < 100; i++ {
		vt.Update(100.05)
	}
	if vt.EWMAVol() > 0.001 {
		t.Errorf("flat prices should give near-zero vol, got %f", vt.EWMAVol())
	}
}

func TestClassifyRegime_Hysteresis(t *testing.T) {
	cfg := VolatilityConfig{VolThreshold: 0.05, VolExitThreshold: 0.04}

	r := ClassifyRegime(0.03, RegimeSideways, cfg)
	if r != RegimeSideways {
		t.Error("should stay Sideways below threshold")
	}

	r = ClassifyRegime(0.06, RegimeSideways, cfg)
	if r != RegimeSpike {
		t.Error("should enter Spike above threshold")
	}

	r = ClassifyRegime(0.045, RegimeSpike, cfg)
	if r != RegimeSpike {
		t.Error("should stay Spike above exit threshold (hysteresis)")
	}

	r = ClassifyRegime(0.035, RegimeSpike, cfg)
	if r != RegimeSideways {
		t.Error("should exit Spike below exit threshold")
	}
}

// ---------------------------------------------------------------------------
// Unit tests: Inventory
// ---------------------------------------------------------------------------

func TestCheckEmergencyCap_LongBreached(t *testing.T) {
	cfg := InventoryConfig{EmergencyCap: d("100")}
	cancelBids, cancelAsks := CheckEmergencyCap(d("150"), cfg)
	if !cancelBids {
		t.Error("long position exceeding cap should cancel bids")
	}
	if cancelAsks {
		t.Error("long position should NOT cancel asks")
	}
}

func TestCheckEmergencyCap_ShortBreached(t *testing.T) {
	cfg := InventoryConfig{EmergencyCap: d("100")}
	cancelBids, cancelAsks := CheckEmergencyCap(d("-150"), cfg)
	if cancelBids {
		t.Error("short position should NOT cancel bids")
	}
	if !cancelAsks {
		t.Error("short position exceeding cap should cancel asks")
	}
}

func TestComputeInventoryRatio_Clamped(t *testing.T) {
	cfg := InventoryConfig{MaxInventory: d("100")}
	r := ComputeInventoryRatio(d("200"), cfg)
	if r != 1.0 {
		t.Errorf("ratio should clamp to 1.0, got %f", r)
	}
}

// ---------------------------------------------------------------------------
// Integration: MASStrategy.Tick
// ---------------------------------------------------------------------------

func TestTick_SidewaysRegime_GeneratesL0toL9(t *testing.T) {
	s := initStrategy(t)
	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)

	out := s.Tick(balancedBook(), nil, now)

	if out.CancelAll {
		t.Fatal("should not cancel all")
	}

	if len(out.Orders) != 20 {
		t.Errorf("sideways tick should produce 20 orders, got %d", len(out.Orders))
	}

	bidCount := countSide(out.Orders, Bid)
	askCount := countSide(out.Orders, Ask)
	if bidCount != 10 || askCount != 10 {
		t.Errorf("expected 10 bids + 10 asks, got %d bids + %d asks", bidCount, askCount)
	}
}

func TestTick_L9_ComplianceFatTail(t *testing.T) {
	s := initStrategy(t)
	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)
	book := balancedBook()

	out := s.Tick(book, nil, now)

	midPrice := book.BestBid.Add(book.BestAsk).Div(d("2"))
	expectedOffset := midPrice.Mul(d("0.0195"))
	expectedBid := midPrice.Sub(expectedOffset)
	expectedAsk := midPrice.Add(expectedOffset)

	l9Bid := findLevel(out.Orders, Bid, L9)
	l9Ask := findLevel(out.Orders, Ask, L9)

	if l9Bid == nil || l9Ask == nil {
		t.Fatal("L9 bid or ask missing from tick output")
	}

	if !l9Bid.Price.Equal(expectedBid) {
		t.Errorf("L9 bid = %s, want %s", l9Bid.Price, expectedBid)
	}
	if !l9Ask.Price.Equal(expectedAsk) {
		t.Errorf("L9 ask = %s, want %s", l9Ask.Price, expectedAsk)
	}
}

func TestTick_SpikeRegime_L4Empty(t *testing.T) {
	s := initStrategy(t)
	s.state.Regime = RegimeSpike
	cfg := testConfig()
	cfg.Volatility.VolThreshold = 0.0001
	cfg.Volatility.VolExitThreshold = 0.00005
	MASConfigPtr.Store(cfg)

	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)
	out := s.Tick(balancedBook(), nil, now)

	for _, o := range out.Orders {
		if o.Level == L4 {
			t.Error("spike regime must have empty L4 buffer zone")
		}
	}
}

func TestTick_SpikeRegime_NearThinDeepThick(t *testing.T) {
	s := initStrategy(t)
	s.state.Regime = RegimeSpike
	cfg := testConfig()
	cfg.Volatility.VolThreshold = 0.0001
	MASConfigPtr.Store(cfg)

	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)
	out := s.Tick(balancedBook(), nil, now)

	nearSize := d("10").Mul(d("0.25"))
	for _, o := range out.Orders {
		if o.Level >= L0 && o.Level <= L3 {
			if !o.Size.Equal(nearSize) {
				t.Errorf("near level %d size = %s, want %s", o.Level, o.Size, nearSize)
			}
		}
	}

	deepSize := d("10").Mul(d("2"))
	for _, o := range out.Orders {
		if o.Level >= L5 && o.Level <= L8 {
			if !o.Size.Equal(deepSize) {
				t.Errorf("deep level %d size = %s, want %s", o.Level, o.Size, deepSize)
			}
		}
	}
}

func TestTick_EmergencyCap_CancelsBids(t *testing.T) {
	s := initStrategy(t)
	s.state.NetPosition = d("300")
	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)

	out := s.Tick(balancedBook(), nil, now)

	if !out.CancelBids {
		t.Error("should cancel bids when long exceeds emergency cap")
	}
	if countSide(out.Orders, Bid) != 0 {
		t.Error("no bid orders should remain after emergency cap")
	}
	if countSide(out.Orders, Ask) == 0 {
		t.Error("ask orders should remain when only bids are capped")
	}
}

func TestTick_InventorySkew_LongPushesDown(t *testing.T) {
	s := initStrategy(t)
	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)
	book := balancedBook()

	flatOut := s.Tick(book, nil, now)

	s2 := initStrategy(t)
	s2.state.NetPosition = d("80")
	longOut := s2.Tick(book, nil, now.Add(time.Second))

	flatBid := findLevel(flatOut.Orders, Bid, L0)
	longBid := findLevel(longOut.Orders, Bid, L0)

	if flatBid == nil || longBid == nil {
		t.Fatal("L0 bid missing")
	}

	if !longBid.Price.LessThan(flatBid.Price) {
		t.Errorf("long inventory should push L0 bid down: flat=%s long=%s", flatBid.Price, longBid.Price)
	}
}

// ---------------------------------------------------------------------------
// Integration: OnFill queue + deferred toxicity
// ---------------------------------------------------------------------------

func TestOnFill_QueuesDrainedInTick(t *testing.T) {
	s := initStrategy(t)
	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)

	s.OnFill(Fill{
		OrderID:   "test-1",
		Price:     d("100.05"),
		Qty:       d("5"),
		Side:      Bid,
		Timestamp: now,
	})

	out := s.Tick(balancedBook(), nil, now.Add(100*time.Millisecond))

	if !out.State.NetPosition.Equal(d("5")) {
		t.Errorf("net position after bid fill should be 5, got %s", out.State.NetPosition)
	}

	s.fillMu.Lock()
	n := len(s.pendingFills)
	s.fillMu.Unlock()
	if n != 0 {
		t.Errorf("pending fills should be drained, got %d", n)
	}
}

func TestTick_DeferredToxicityEval(t *testing.T) {
	s := initStrategy(t)
	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)
	book := balancedBook()

	s.Tick(book, nil, now)

	s.OnFill(Fill{
		OrderID:   "toxic-1",
		Price:     d("100.05"),
		Qty:       d("5"),
		Side:      Bid,
		Timestamp: now.Add(1 * time.Second),
	})

	s.Tick(book, nil, now.Add(2*time.Second))
	if len(s.awaitingEval) != 1 {
		t.Errorf("fill should be awaiting eval, got %d entries", len(s.awaitingEval))
	}

	adverseBook := OrderBook{
		BestBid:   d("99.90"),
		BestAsk:   d("99.95"),
		BidQty:    d("50"),
		AskQty:    d("50"),
		Timestamp: now.Add(3 * time.Second),
	}

	s.Tick(adverseBook, nil, now.Add(3*time.Second))

	s.Tick(adverseBook, nil, now.Add(7*time.Second))

	if len(s.awaitingEval) != 0 {
		t.Errorf("fill should have been evaluated, still awaiting: %d", len(s.awaitingEval))
	}
}

func TestTick_ToxicityPause_KeepsL9(t *testing.T) {
	s := initStrategy(t)
	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)

	s.toxicity.RecordFill(Bid, true, now)

	out := s.Tick(balancedBook(), nil, now.Add(time.Millisecond))

	l9Bid := findLevel(out.Orders, Bid, L9)
	if l9Bid == nil {
		t.Error("L9 bid must survive toxicity pause (compliance anchor)")
	}

	for _, o := range out.Orders {
		if o.Side == Bid && o.Level != L9 {
			t.Errorf("bid level %d should be paused, but found in output", o.Level)
		}
	}

	askCount := countSide(out.Orders, Ask)
	if askCount != 10 {
		t.Errorf("ask side should have 10 levels during bid pause, got %d", askCount)
	}
}

// ---------------------------------------------------------------------------
// Unit tests: PriceAtLevel
// ---------------------------------------------------------------------------

func TestPriceAtLevel_BidBelowFairValue(t *testing.T) {
	fv := d("100.00")
	spread := d("0.05")
	p := PriceAtLevel(Bid, L0, fv, spread)
	if !p.Equal(d("99.95")) {
		t.Errorf("L0 bid = %s, want 99.95", p)
	}
}

func TestPriceAtLevel_AskAboveFairValue(t *testing.T) {
	fv := d("100.00")
	spread := d("0.05")
	p := PriceAtLevel(Ask, L0, fv, spread)
	if !p.Equal(d("100.05")) {
		t.Errorf("L0 ask = %s, want 100.05", p)
	}
}

func TestPriceAtLevel_DeeperLevelsWider(t *testing.T) {
	fv := d("100.00")
	spread := d("0.05")
	l0 := PriceAtLevel(Bid, L0, fv, spread)
	l5 := PriceAtLevel(Bid, L5, fv, spread)
	if !l5.LessThan(l0) {
		t.Errorf("L5 bid (%s) should be lower than L0 bid (%s)", l5, l0)
	}
}

// ---------------------------------------------------------------------------
// Unit tests: ComputeFairValue
// ---------------------------------------------------------------------------

func TestComputeFairValue_ZeroOFI(t *testing.T) {
	micro := d("100.05")
	cfg := FairValueConfig{OFIAlpha: d("0.5"), TickSize: d("0.01")}
	fv := ComputeFairValue(micro, d("0"), cfg)
	if !fv.Equal(micro) {
		t.Errorf("zero OFI should return micro-price, got %s", fv)
	}
}

func TestComputeFairValue_PositiveOFI(t *testing.T) {
	micro := d("100.05")
	cfg := FairValueConfig{OFIAlpha: d("0.5"), TickSize: d("0.01")}
	fv := ComputeFairValue(micro, d("1"), cfg)
	if !fv.GreaterThan(micro) {
		t.Errorf("positive OFI should raise fair value above micro-price")
	}
}

// ---------------------------------------------------------------------------
// Strategy interface compliance
// ---------------------------------------------------------------------------

func TestMASStrategy_ImplementsStrategy(t *testing.T) {
	var _ Strategy = (*MASStrategy)(nil)
}

func TestMASStrategy_Name(t *testing.T) {
	s := NewMASStrategy(nil)
	if s.Name() != "MAS-CapitalPreservation" {
		t.Errorf("unexpected name: %s", s.Name())
	}
}

func TestTick_NilConfig_CancelAll(t *testing.T) {
	s := NewMASStrategy(nil)
	MASConfigPtr.Store(nil)
	now := time.Date(2025, 1, 1, 12, 0, 0, 0, time.UTC)
	out := s.Tick(balancedBook(), nil, now)
	if !out.CancelAll {
		t.Error("nil config should trigger CancelAll")
	}
}
