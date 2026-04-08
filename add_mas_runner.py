import re

main_path = '/home/ben/project/projects/mm-platform-bot/cmd/main.go'
with open(main_path, 'r') as f:
    content = f.read()

if 'case "mas":' not in content:
    content = content.replace(
        'case "depth-filler":\n\t\teng = createDepthFillerEngine(cfg, exch, redis, mongo, exchangeName, botID)\n\t\tlog.Println("Mode: DEPTH-FILLER (event-driven)")',
        'case "depth-filler":\n\t\teng = createDepthFillerEngine(cfg, exch, redis, mongo, exchangeName, botID)\n\t\tlog.Println("Mode: DEPTH-FILLER (event-driven)")\n\tcase "mas":\n\t\teng = createMASEngine(cfg, exch, redis, mongo, exchangeName, botID)\n\t\tlog.Println("Mode: MAS (Capital Preservation)")'
    )
    content = content.replace(
        "must be 'simple-maker', 'spike-maker', 'spike-maker-v2', or 'depth-filler'",
        "must be 'simple-maker', 'spike-maker', 'spike-maker-v2', 'depth-filler', or 'mas'"
    )
    
    mas_factory = """
func createMASEngine(
	cfg *config.Config,
	exch exchange.Exchange,
	redis *store.RedisStore,
	mongo *store.MongoStore,
	exchangeName string,
	botID string,
) *engine.Engine {
	// For now, load default config. In a real scenario, this would come from a YAML unmarshal
	// mapping to strategy.MASConfig
	
	// Create strategy
	// strat := strategy.NewMASStrategy(masCfg)
	
	// Create engine
	// engineCfg := engine.Config{ ... }
	// return engine.NewEngine(engineCfg, strat, exch, executor, redis, mongo)
	log.Fatalf("MAS Engine Factory not yet fully implemented in bot package")
	return nil
}
"""
    content += mas_factory
    
    with open(main_path, 'w') as f:
        f.write(content)
