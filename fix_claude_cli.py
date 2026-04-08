import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# The fix is to stop using `--print` or figure out a way to get raw output
# Looking at the config.yaml for the claude backend:
if 'claude' in config.get('backends', {}):
    args = config['backends']['claude'].get('args', [])
    if '--print' in args:
        args.remove('--print')
        # We need something to replace --print that gives raw output without stripping
        # Let's try adding --raw-output if it's supported, or just running without --print
        args.append('--raw-output')
    config['backends']['claude']['args'] = args

with open('config.yaml', 'w') as f:
    yaml.dump(config, f)
