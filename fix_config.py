import yaml
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)
config['agents']['BackendDev']['backend'] = 'claude'
config['agents']['BackendDev']['model'] = 'claude-sonnet-4-6'
with open('config.yaml', 'w') as f:
    yaml.dump(config, f)
