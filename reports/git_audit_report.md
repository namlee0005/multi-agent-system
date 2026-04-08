# Git Security Audit Report

**Date:** 2026-03-25
**Auditor:** DevOps Agent
**Scope:** `multi-agent-system` + 3 sibling projects
**Status:** CRITICAL FINDING — Immediate action required

---

## Executive Summary

| Project | Audited | Critical | High | Medium | Low |
|---|---|---|---|---|---|
| multi-agent-system | ✅ | 1 | 1 | 1 | 0 |
| ai-influencer-factory | ❌ Not found | — | — | — | — |
| liquidity-guard-bot | ❌ Not found | — | — | — | — |
| cyber-neon-roguelike | ❌ Not found | — | — | — | — |

---

## CRITICAL: Hardcoded PAT in `.git/config`

**Severity:** CRITICAL
**File:** `.git/config`, `remote.origin.url`

The remote URL embeds a GitHub Personal Access Token directly:

```
url = https://ghp_***REDACTED***@github.com/namlee0005/multi-agent-system.git
```

This token is stored in plaintext on disk, visible to any process with filesystem access, and would be exposed in any git diagnostic output, logs, or error messages.

### Immediate Remediation (do this now)

```bash
# 1. Rotate the token immediately on GitHub
#    → github.com → Settings → Developer settings → Personal access tokens → Revoke

# 2. Remove the token from the remote URL
git remote set-url origin https://github.com/namlee0005/multi-agent-system.git

# 3. Verify no token remains
git remote -v
cat .git/config
```

---

## HIGH: PAT Usage — Wrong Auth Pattern for CI

**Severity:** HIGH

A user PAT is the wrong credential type for any non-human context. PATs carry the full permission scope of the user account, do not auto-rotate, and if the token was used in CI workflows it has been broadcast to GitHub's runner infrastructure.

### Fix: Replace with SSH (human use) or GitHub App token (CI use)

**For local developer access (SSH — recommended):**

```bash
# Generate ed25519 key (passphrase-protected)
ssh-keygen -t ed25519 -C "ben@openclaw.ai" -f ~/.ssh/github_ed25519

# Add to GitHub: Settings → SSH and GPG keys → New SSH key
# Then update remote to SSH
git remote set-url origin git@github.com:namlee0005/multi-agent-system.git
```

**For CI/CD (GitHub App token — required):**

```yaml
# .github/workflows/ci.yml
- uses: actions/create-github-app-token@v1
  id: app-token
  with:
    app-id: ${{ vars.APP_ID }}
    private-key: ${{ secrets.APP_PRIVATE_KEY }}

- uses: actions/checkout@v4
  with:
    token: ${{ steps.app-token.outputs.token }}
```

GitHub App tokens auto-rotate per-run and scope permissions to the installation. Never use a user PAT in CI.

---

## MEDIUM: `.gitignore` — Incomplete Coverage

**Severity:** MEDIUM
**File:** `.gitignore` (present, but missing entries)

Current coverage: `__pycache__/`, `*.pyc`, `.env`
Missing critical exclusions:

```gitignore
# Add to .gitignore
*.env.*
.env.local
.env.*.local
*.key
*.pem
*.p8
*.pfx
secrets/
reports/           # Generated artifacts — optional but recommended
logs/              # Session logs may contain token/session data
dist/
build/
*.egg-info/
.venv/
venv/
.pytest_cache/
.coverage
htmlcov/
```

**Note on `logs/`:** Session JSON logs at `logs/session-{id}.json` contain `CLICallResult` fields including session IDs and potentially prompt content. These should not be committed.

---

## INFO: Sibling Projects Not Found

`/home/ben/projects/ai-influencer-factory`, `liquidity-guard-bot`, and `cyber-neon-roguelike` do not exist at the expected paths. Audit of these projects was not possible. Verify the paths and re-run audit once located.

---

## Workflow Scope Issue — Deploy Keys vs GitHub Apps

The "workflow scope" issue (insufficient permissions for `GITHUB_TOKEN` to trigger downstream workflows) has two correct solutions:

### Option A: GitHub Deploy Key (read-only push — simple)

Use when the pipeline only needs to push commits or tags to a single repo.

```bash
# Generate a dedicated deploy key
ssh-keygen -t ed25519 -f ~/.ssh/deploy_multi_agent -N ""

# Add public key to: repo → Settings → Deploy keys → Add deploy key
# Add private key to: repo → Settings → Secrets → DEPLOY_KEY

# Use in workflow:
- uses: webfactory/ssh-agent@v0.9.0
  with:
    ssh-private-key: ${{ secrets.DEPLOY_KEY }}
```

Deploy keys are repo-scoped and read-only by default. Grant write only if the pipeline must push (e.g., auto-tagging).

### Option B: GitHub App (recommended for cross-repo or workflow triggers)

Use when `workflow_dispatch` or `repository_dispatch` must trigger across repos, or when you need fine-grained permission control.

```yaml
- uses: actions/create-github-app-token@v1
  id: app-token
  with:
    app-id: ${{ vars.APP_ID }}
    private-key: ${{ secrets.APP_PRIVATE_KEY }}
    # Optionally scope to specific repos:
    # repositories: "repo-a,repo-b"

- name: Trigger downstream workflow
  run: |
    gh workflow run deploy.yml --repo namlee0005/other-repo
  env:
    GH_TOKEN: ${{ steps.app-token.outputs.token }}
```

**Decision:** If this is a single-repo concern, use a Deploy Key. If cross-repo workflow triggers are needed, use a GitHub App. The App adds ~5 minutes of setup but eliminates PAT dependency permanently.

---

## Secret Leak Detection — Add as Pipeline Gate

Add `gitleaks` as a required pre-merge check to catch any future credential commits:

```yaml
# .github/workflows/security.yml
name: Secret Scan
on: [push, pull_request]
jobs:
  gitleaks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: gitleaks/gitleaks-action@v2
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## Remediation Priority

| Priority | Action | Effort |
|---|---|---|
| **P0 — Now** | Revoke the exposed PAT on GitHub | 2 min |
| **P0 — Now** | Remove token from `git remote set-url` | 1 min |
| **P1 — Today** | Switch to SSH key (local) or GitHub App (CI) | 15 min |
| **P2 — This week** | Expand `.gitignore` with missing entries | 5 min |
| **P2 — This week** | Add `gitleaks` scan to CI pipeline | 10 min |
| **P3 — Backlog** | Locate and audit 3 missing sibling projects | TBD |
