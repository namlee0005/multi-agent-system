import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

if 'claude' in config.get('backends', {}):
    args = config['backends']['claude'].get('args', [])
    if '--print' not in args:
        args.insert(0, '--print')
    if '--raw-output' in args:
        args.remove('--raw-output')
    config['backends']['claude']['args'] = args

with open('config.yaml', 'w') as f:
    yaml.dump(config, f)
