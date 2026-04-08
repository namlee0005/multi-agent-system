import re

test_path = '/home/ben/project/projects/mm-platform-bot/internal/strategy/mas_strategy_test.go'

with open(test_path, 'r') as f:
    content = f.read()

# Replace wrong import path
content = content.replace('"mm-platform-engine/pkg/exchange"', '"mm-platform-engine/internal/exchange"')

with open(test_path, 'w') as f:
    f.write(content)
