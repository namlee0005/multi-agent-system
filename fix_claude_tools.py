import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

if 'claude' in config.get('backends', {}):
    args = config['backends']['claude'].get('args', [])
    
    # Remove existing --tools if any
    try:
        idx = args.index('--tools')
        args.pop(idx)
        args.pop(idx) # the value
    except ValueError:
        pass
        
    # Add --tools "" to completely disable Claude's native tools
    # This forces the LLM to use OUR <write_file> tag instead of the native Write tool
    # which causes the summarization bug.
    args.extend(['--tools', ''])
    
    config['backends']['claude']['args'] = args

with open('config.yaml', 'w') as f:
    yaml.dump(config, f)

print("Config updated to disable native tools.")
