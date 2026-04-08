import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

for agent in config.get('agents', {}):
    config['agents'][agent]['model'] = 'claude-opus-4-6'
    config['agents'][agent]['backend'] = 'claude' # Ensure backend is claude

with open('config.yaml', 'w') as f:
    yaml.dump(config, f)
