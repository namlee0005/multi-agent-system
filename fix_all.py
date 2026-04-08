import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# The most stable approach without rewriting the entire cli_session parser
# is to disable the --print flag, use standard interactive mode via pexpect or subprocess
# BUT since we've already done so much, let's just write the MAS.go strategy directly.

# Re-enable the normal claude config
if 'claude' in config.get('backends', {}):
    args = config['backends']['claude'].get('args', [])
    if '--print' not in args:
        args.insert(0, '--print')
    if '--output-format' not in args:
        args.extend(['--output-format', 'json'])
    # Clean up tools arg
    if '--tools' in args:
        idx = args.index('--tools')
        args.pop(idx)
        args.pop(idx)
    config['backends']['claude']['args'] = args

with open('config.yaml', 'w') as f:
    yaml.dump(config, f)
