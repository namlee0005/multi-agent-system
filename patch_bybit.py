import re

file_path = '/home/ben/project/projects/mm-platform-bot/internal/exchange/ccxt_adapter.go'
with open(file_path, 'r') as f:
    content = f.read()

# The user provided multiple stack traces showing different goroutines.
# Goroutine 346: concurrent map read/write in ccxt SafeValueN during NewOrderArray inside WatchOrders.
# Wait, this means WatchOrders itself inside CCXT is still having map race conditions.
# It's an internal CCXT issue where its caching/internal maps aren't thread-safe when accessed 
# simultaneously even across different WS clients, OR there's shared state in ccxtpro.

# To mitigate CCXT internal map races, we can wrap ccxt calls in a global mutex or exchange-level mutex.
new_struct = """type CCXTAdapter struct {
	rest         ccxt.IExchange    // REST API client
	ws           ccxtpro.IExchange // WS client for creating/canceling orders
	wsOrders     ccxtpro.IExchange // Dedicated WS client for WatchOrders
	wsTrades     ccxtpro.IExchange // Dedicated WS client for WatchMyTrades
	exchangeName string
	symbol       string // CCXT format: BASE/QUOTE
	nativeSymbol string // Exchange format: BASEQUOTE
	handlers     UserStreamHandlers

	// WebSocket control
	ctx       context.Context
	cancel    context.CancelFunc
	wsRunning bool
	wsMu      sync.RWMutex

	// Global CCXT lock to prevent internal map race conditions in go-ccxt
	ccxtLock sync.Mutex"""

content = content.replace("type CCXTAdapter struct {\n\trest         ccxt.IExchange    // REST API client\n\tws           ccxtpro.IExchange // WS client for creating/canceling orders\n\twsOrders     ccxtpro.IExchange // Dedicated WS client for WatchOrders\n\twsTrades     ccxtpro.IExchange // Dedicated WS client for WatchMyTrades\n\texchangeName string\n\tsymbol       string // CCXT format: BASE/QUOTE\n\tnativeSymbol string // Exchange format: BASEQUOTE\n\thandlers     UserStreamHandlers\n\n\t// WebSocket control\n\tctx       context.Context\n\tcancel    context.CancelFunc\n\twsRunning bool\n\twsMu      sync.RWMutex", new_struct)

# Add lock around WatchOrders
content = content.replace('orders, err := c.wsOrders.WatchOrders(ccxt.WithWatchOrdersSymbol(c.symbol))', 'c.ccxtLock.Lock()\n\t\t\torders, err := c.wsOrders.WatchOrders(ccxt.WithWatchOrdersSymbol(c.symbol))\n\t\t\tc.ccxtLock.Unlock()')

# Add lock around WatchMyTrades
content = content.replace('trades, err := c.wsTrades.WatchMyTrades(ccxt.WithWatchMyTradesSymbol(c.symbol))', 'c.ccxtLock.Lock()\n\t\t\ttrades, err := c.wsTrades.WatchMyTrades(ccxt.WithWatchMyTradesSymbol(c.symbol))\n\t\t\tc.ccxtLock.Unlock()')

# Add lock around CreateOrderWs
content = content.replace('result, err = c.ws.CreateOrderWs(', 'c.ccxtLock.Lock()\n\t\tresult, err = c.ws.CreateOrderWs(')
content = content.replace('if err != nil {\n\t\t\treturn nil, fmt.Errorf("CreateOrderWs error: %w", err)\n\t\t}', 'c.ccxtLock.Unlock()\n\t\tif err != nil {\n\t\t\treturn nil, fmt.Errorf("CreateOrderWs error: %w", err)\n\t\t}')

# Add lock around CancelOrderWs
content = content.replace('_, err := c.ws.CancelOrderWs(', 'c.ccxtLock.Lock()\n\t_, err := c.ws.CancelOrderWs(')
content = content.replace('ccxt.WithCancelOrderWsParams(map[string]interface{}{"orderLinkId": orderID}),\n\t)', 'ccxt.WithCancelOrderWsParams(map[string]interface{}{"orderLinkId": orderID}),\n\t)\n\tc.ccxtLock.Unlock()')

with open(file_path, 'w') as f:
    f.write(content)
