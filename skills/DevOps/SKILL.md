# DevOps Skill Constraints

## Git & Auth
- SSH ed25519 for humans; GitHub App tokens for CI — never user PATs in pipelines
- Deploy keys are read-only unless the pipeline must push (tagging only)
- `gitleaks`/`trufflehog` runs as a pipeline gate before any merge to main
- Secrets in CI vault scoped to environment — never in `.yml`, Dockerfile ARGs, or committed `.env`

## CI/CD Invariants
- Feature branch CI target: ≤90s; order: lint → test → build (fail fast)
- All deployment pipelines must be idempotent — re-running must be safe
- Pin action versions to commit SHA, not floating tag
- Matrix builds only when the project ships to multiple platforms

## Repo Sync
- Fork upstream: automate via scheduled workflow, not manual merge
- Submodules: pin to tags; update in a dedicated maintenance PR only
