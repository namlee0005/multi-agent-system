import re

file_path = '/home/ben/project/projects/mm-platform-bot/internal/config/config.go'
with open(file_path, 'r') as f:
    content = f.read()

# Add MAS config struct to SimpleConfig
mas_struct = """
	// MAS Strategy specific configuration (loaded from JSON field in Mongo)
	MASConfig string `json:"mas_config,omitempty" bson:"mas_config,omitempty"`
"""

if 'MASConfig string' not in content:
    content = re.sub(r'SkewK\s+float64\s+`json:"skew_k,omitempty"\s+bson:"skew_k,omitempty"`', 'SkewK              float64 `json:"skew_k,omitempty" bson:"skew_k,omitempty"`\n' + mas_struct, content)
    with open(file_path, 'w') as f:
        f.write(content)

