import re

file_path = '/home/ben/project/projects/mm-platform-bot/internal/exchange/ccxt_adapter.go'
with open(file_path, 'r') as f:
    content = f.read()

# Update struct
old_struct = """type CCXTAdapter struct {
	rest         ccxt.IExchange    // REST API client
	ws           ccxtpro.IExchange // Single WS client for WatchOrders + trading
	exchangeName string"""
new_struct = """type CCXTAdapter struct {
	rest         ccxt.IExchange    // REST API client
	ws           ccxtpro.IExchange // WS client for creating/canceling orders
	wsOrders     ccxtpro.IExchange // Dedicated WS client for WatchOrders
	wsTrades     ccxtpro.IExchange // Dedicated WS client for WatchMyTrades
	exchangeName string"""
content = content.replace(old_struct, new_struct)

# Update constructor vars
old_vars = """	var rest ccxt.IExchange
	var ws ccxtpro.IExchange

	switch exchangeName {"""
new_vars = """	var rest ccxt.IExchange
	var ws, wsOrders, wsTrades ccxtpro.IExchange

	switch exchangeName {"""
content = content.replace(old_vars, new_vars)

# Update constructors
content = content.replace('rest = ccxt.NewBybit(nil)\n\t\tws = ccxtpro.NewBybit(nil)', 'rest = ccxt.NewBybit(nil)\n\t\tws = ccxtpro.NewBybit(nil)\n\t\twsOrders = ccxtpro.NewBybit(nil)\n\t\twsTrades = ccxtpro.NewBybit(nil)')
content = content.replace('rest = ccxt.NewBinance(nil)\n\t\tws = ccxtpro.NewBinance(nil)', 'rest = ccxt.NewBinance(nil)\n\t\tws = ccxtpro.NewBinance(nil)\n\t\twsOrders = ccxtpro.NewBinance(nil)\n\t\twsTrades = ccxtpro.NewBinance(nil)')
content = content.replace('rest = ccxt.NewGate(nil)\n\t\tws = ccxtpro.NewGate(nil)', 'rest = ccxt.NewGate(nil)\n\t\tws = ccxtpro.NewGate(nil)\n\t\twsOrders = ccxtpro.NewGate(nil)\n\t\twsTrades = ccxtpro.NewGate(nil)')
content = content.replace('rest = ccxt.NewGateio(nil)\n\t\tws = ccxtpro.NewGateio(nil)', 'rest = ccxt.NewGateio(nil)\n\t\tws = ccxtpro.NewGateio(nil)\n\t\twsOrders = ccxtpro.NewGateio(nil)\n\t\twsTrades = ccxtpro.NewGateio(nil)')
content = content.replace('rest = ccxt.NewKucoin(nil)\n\t\tws = ccxtpro.NewKucoin(nil)', 'rest = ccxt.NewKucoin(nil)\n\t\tws = ccxtpro.NewKucoin(nil)\n\t\twsOrders = ccxtpro.NewKucoin(nil)\n\t\twsTrades = ccxtpro.NewKucoin(nil)')
content = content.replace('rest = ccxt.NewOkx(nil)\n\t\tws = ccxtpro.NewOkx(nil)', 'rest = ccxt.NewOkx(nil)\n\t\tws = ccxtpro.NewOkx(nil)\n\t\twsOrders = ccxtpro.NewOkx(nil)\n\t\twsTrades = ccxtpro.NewOkx(nil)')
content = content.replace('rest = ccxt.NewMexc(nil)\n\t\tws = ccxtpro.NewMexc(nil)', 'rest = ccxt.NewMexc(nil)\n\t\tws = ccxtpro.NewMexc(nil)\n\t\twsOrders = ccxtpro.NewMexc(nil)\n\t\twsTrades = ccxtpro.NewMexc(nil)')
content = content.replace('rest = ccxt.NewHtx(nil)\n\t\tws = ccxtpro.NewHtx(nil)', 'rest = ccxt.NewHtx(nil)\n\t\tws = ccxtpro.NewHtx(nil)\n\t\twsOrders = ccxtpro.NewHtx(nil)\n\t\twsTrades = ccxtpro.NewHtx(nil)')
content = content.replace('rest = ccxt.NewBitget(nil)\n\t\tws = ccxtpro.NewBitget(nil)', 'rest = ccxt.NewBitget(nil)\n\t\tws = ccxtpro.NewBitget(nil)\n\t\twsOrders = ccxtpro.NewBitget(nil)\n\t\twsTrades = ccxtpro.NewBitget(nil)')

# Update SetApiKey section
old_creds = """	// Set credentials
	rest.SetApiKey(apiKey)
	rest.SetSecret(secret)
	ws.SetApiKey(apiKey)
	ws.SetSecret(secret)

	// Set sandbox mode if needed
	if sandbox {
		rest.SetSandboxMode(true)
		ws.SetSandboxMode(true)
	}"""
new_creds = """	// Set credentials
	for _, client := range []ccxt.IExchange{rest, ws, wsOrders, wsTrades} {
		client.SetApiKey(apiKey)
		client.SetSecret(secret)
		if sandbox {
			client.SetSandboxMode(true)
		}
	}"""
content = content.replace(old_creds, new_creds)

# Update adapter initialization
old_adapter = """	adapter := &CCXTAdapter{
		rest:         rest,
		ws:           ws,
		exchangeName: exName,"""
new_adapter = """	adapter := &CCXTAdapter{
		rest:         rest,
		ws:           ws,
		wsOrders:     wsOrders,
		wsTrades:     wsTrades,
		exchangeName: exName,"""
content = content.replace(old_adapter, new_adapter)

# Update watchOrders and watchMyTrades
content = content.replace('orders, err := c.ws.WatchOrders(ccxt.WithWatchOrdersSymbol(c.symbol))', 'orders, err := c.wsOrders.WatchOrders(ccxt.WithWatchOrdersSymbol(c.symbol))')
content = content.replace('trades, err := c.ws.WatchMyTrades(ccxt.WithWatchMyTradesSymbol(c.symbol))', 'trades, err := c.wsTrades.WatchMyTrades(ccxt.WithWatchMyTradesSymbol(c.symbol))')

# LoadMarkets
content = content.replace('c.ws.LoadMarkets()', 'c.ws.LoadMarkets()\n\tc.wsOrders.LoadMarkets()\n\tc.wsTrades.LoadMarkets()')

with open(file_path, 'w') as f:
    f.write(content)
