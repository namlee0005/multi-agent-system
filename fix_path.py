import os
import glob

# The AI generated imports using mm-platform-engine/pkg/exchange but it seems it should be mm-platform-engine/internal/exchange
# Let's check what the actual imports are in the existing files.
with open('/home/ben/project/projects/mm-platform-bot/internal/strategy/spike_maker.go', 'r') as f:
    content = f.read()
    if 'mm-platform-engine/internal/exchange' in content:
        print("Using internal/exchange")
    elif 'mm-platform-engine/pkg/exchange' in content:
        print("Using pkg/exchange")
    else:
        print("Finding imports...")
        import re
        matches = re.findall(r'mm-platform-engine/[^\s"]+', content)
        print(set(matches))
