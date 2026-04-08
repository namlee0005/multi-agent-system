package strategy

import (
	"github.com/shopspring/decimal"
)

// Order represents a single quote to be placed on the CLOB.
type Order struct {
	Side  Side
	Level DepthLevel
	Price decimal.Decimal
	Size  decimal.Decimal
}

// ApplyInventorySkew shifts quote prices to discourage adding to a directional
// position. Long inventory pushes bids down (less aggressive) and asks down
// (more aggressive to unwind). Short inventory does the inverse.
//
// skew_offset = inventoryRatio * max_skew_ticks * tick_size
//   - Bids:  price -= skew_offset  (less aggressive when long)
//   - Asks:  price -= skew_offset  (more aggressive when long, i.e. invites sells)
//
// inventoryRatio is in [-1, +1] where +1 = at max long, -1 = at max short.
func ApplyInventorySkew(orders []Order, inventoryRatio float64, cfg InventoryConfig, tickSize decimal.Decimal) []Order {
	if len(orders) == 0 {
		return orders
	}

	maxSkew := decimal.NewFromInt(int64(cfg.MaxSkewTicks))
	ratio := decimal.NewFromFloat(inventoryRatio)
	skewOffset := ratio.Mul(maxSkew).Mul(tickSize)

	result := make([]Order, len(orders))
	for i, o := range orders {
		result[i] = Order{
			Side:  o.Side,
			Level: o.Level,
			Size:  o.Size,
		}
		// Both sides shift in the same direction: positive inventory pushes
		// all prices down (discourages buying, encourages selling).
		result[i].Price = o.Price.Sub(skewOffset)
	}
	return result
}

// CheckEmergencyCap determines which sides must be cancelled when the net
// position breaches the emergency hard cap.
//
// If netPosition > +emergencyCap  => cancelBids (stop buying)
// If netPosition < -emergencyCap  => cancelAsks (stop selling)
//
// Both can be true only if emergencyCap is zero (degenerate config).
func CheckEmergencyCap(netPosition decimal.Decimal, cfg InventoryConfig) (cancelBids, cancelAsks bool) {
	if cfg.EmergencyCap.IsZero() {
		return true, true
	}
	negCap := cfg.EmergencyCap.Neg()

	if netPosition.GreaterThan(cfg.EmergencyCap) {
		cancelBids = true
	}
	if netPosition.LessThan(negCap) {
		cancelAsks = true
	}
	return cancelBids, cancelAsks
}

// ComputeInventoryRatio returns netPosition / maxInventory clamped to [-1, +1].
// Used to feed ApplyInventorySkew. Returns 0 if maxInventory is zero.
func ComputeInventoryRatio(netPosition decimal.Decimal, cfg InventoryConfig) float64 {
	if cfg.MaxInventory.IsZero() {
		return 0
	}
	ratio, _ := netPosition.Div(cfg.MaxInventory).Float64()
	if ratio > 1.0 {
		return 1.0
	}
	if ratio < -1.0 {
		return -1.0
	}
	return ratio
}
