import re

file_path = '/home/ben/project/projects/mm-platform-bot/internal/strategy/mas/mas_strategy.go'
with open(file_path, 'r') as f:
    content = f.read()

# Update applyComplianceFatTail to respect EnforceInSpike config
# We need to add logic that if EnforceInSpike is false and we are in Spike regime, we push L9 out further
# e.g., to 3% or just let it float with the spread.

old_func = """// applyComplianceFatTail overrides L9 bid/ask to sit exactly at
// ComplianceFatTailPct (default 1.95%) from mid-price.
// L9 is the compliance anchor and survives toxicity pauses.
// Only the circuit breaker or emergency cap may remove it.
func (s *MASStrategy) applyComplianceFatTail(orders []Order, midPrice decimal.Decimal) []Order {
	pct := s.quoteCfg.ComplianceFatTailPct
	if pct.IsZero() {
		pct = decimal.NewFromFloat(0.0195)
	}

	offset := midPrice.Mul(pct)
	l9Bid := midPrice.Sub(offset)
	l9Ask := midPrice.Add(offset)"""

new_func = """// applyComplianceFatTail overrides L9 bid/ask to sit exactly at
// ComplianceFatTailPct (default 1.95%) from mid-price during normal regimes.
// If EnforceInSpike is false and we are in a Spike, it pushes L9 out to 5% (safety net).
// L9 is the compliance anchor and survives toxicity pauses.
// Only the circuit breaker or emergency cap may remove it.
func (s *MASStrategy) applyComplianceFatTail(orders []Order, midPrice decimal.Decimal, cfg *MASConfig, regime VolatilityRegime) []Order {
	pct := s.quoteCfg.ComplianceFatTailPct
	if pct.IsZero() {
		pct = decimal.NewFromFloat(0.0195)
	}

	// If in spike and we don't enforce compliance, throw L9 way out of bounds (e.g., 5%) to avoid getting filled
	if regime == RegimeSpike && !cfg.Compliance.EnforceInSpike {
		pct = decimal.NewFromFloat(0.05) // Push out to 5%
	}

	offset := midPrice.Mul(pct)
	l9Bid := midPrice.Sub(offset)
	l9Ask := midPrice.Add(offset)"""

content = content.replace(old_func, new_func)

# Update the call site in Tick
content = content.replace('orders = s.applyComplianceFatTail(orders, midPrice)', 'orders = s.applyComplianceFatTail(orders, midPrice, cfg, s.state.Regime)')

with open(file_path, 'w') as f:
    f.write(content)
