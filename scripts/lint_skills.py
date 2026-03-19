#!/usr/bin/env python3
"""
Enforce ≤200-token limit on all skills/*/SKILL.md files.
Uses tiktoken cl100k_base encoding (Claude-compatible).

Exit codes:
  0 — all files pass
  1 — one or more files exceed the token limit
"""
import sys
import os
import glob

try:
    import tiktoken
except ImportError:
    print("ERROR: tiktoken not installed. Run: pip install tiktoken", file=sys.stderr)
    sys.exit(1)

TOKEN_LIMIT = 200
ENCODING = "cl100k_base"
SKILLS_GLOB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills", "*", "SKILL.md")

enc = tiktoken.get_encoding(ENCODING)

violations: list[tuple[str, int]] = []

for skill_file in sorted(glob.glob(SKILLS_GLOB)):
    with open(skill_file, "r") as f:
        content = f.read()
    token_count = len(enc.encode(content))
    rel_path = os.path.relpath(skill_file)
    if token_count > TOKEN_LIMIT:
        violations.append((rel_path, token_count))
        print(f"FAIL  {rel_path}  ({token_count} tokens > {TOKEN_LIMIT} limit)")
    else:
        print(f"OK    {rel_path}  ({token_count} tokens)")

if violations:
    print(f"\n{len(violations)} file(s) exceed the {TOKEN_LIMIT}-token limit.", file=sys.stderr)
    sys.exit(1)

print(f"\nAll skill files pass the {TOKEN_LIMIT}-token limit.")
sys.exit(0)