# Multi-Agent System (MAS)

A debate-driven technical advisory framework where specialized AI agents propose, challenge, and synthesize recommendations in parallel — producing well-reasoned architecture decisions with built-in adversarial review.

## Features

- **Parallel Debate** — Round agents run concurrently via `ThreadPoolExecutor`; no sequential bottleneck
- **CLI Session Persistence** — Each agent resumes its own server-side context across rounds via `--resume`, cutting repeated-context token costs by ~20–40%
- **Compression Gate** — Round 1 proposals are compressed before Round 2; ~60–70% token reduction on challenge inputs
- **Skill Injection** — Per-agent `SKILL.md` files inject role-specific behavioral constraints without polluting core personas
- **Hardened Reliability** — Structured exception hierarchy, fail-fast binary validation, session log integrity checks, and a regression suite covering concurrency and error paths
- **Artifact Gate** — `<write_file>` outputs are reviewed by a dedicated `CodeReviewer` agent (PASS/WARN/FAIL) before being written to disk
- **Multi-Backend** — Runs against Claude CLI, Gemini CLI, or any CLI-exposed model; mixed backends per agent supported

## How It Works

```
User Request
    ↓
Planner → selects 3–5 relevant specialist agents
    ↓
Round 1 (parallel) — each agent proposes their perspective
    ↓
Compression Gate — proposals compressed to bullet summaries
    ↓
Round 2 (parallel) — agents challenge and refine
    ↓
Synthesis — Planner integrates all views → final recommendation
    ↓
Artifact Gate — any generated files reviewed by CodeReviewer
    ↓
report_*.md saved to disk
```

## Agents

| Agent | Role | Temperature |
|-------|------|-------------|
| **Planner** | Moderator — selects agents, synthesizes output | 0.5 |
| **Researcher** | Evidence synthesis, real-world precedents | 0.7 |
| **Architect** | System design, data models, service boundaries | 0.7 |
| **BackendDev** | Language/framework/database selection | 0.8 |
| **FrontendDev** | UI framework, accessibility, bundle strategy | 0.8 |
| **DevOps** | Git workflow, CI/CD pipelines, secrets hygiene, deployment automation | 0.7 |
| **Security** | Threat modeling, OWASP, auth/authz | 0.6 |
| **Skeptic** | Devil's advocate — surfaces hidden assumptions | 0.9 |
| **Tester** | Runtime testing, edge cases, test script generation | 0.4 |
| **VisualArtist** | Stable Diffusion prompt engineering (subject, style, lighting, camera) | 0.85 |
| **CodeReviewer** | Artifact gate — PASS/WARN/FAIL on generated files | 0.3 |

## Installation

```bash
pip install pyyaml pytest tiktoken
```

At least one LLM backend CLI is required:

```bash
# Claude CLI (recommended)
npm install -g @anthropic-ai/claude-code

# Gemini CLI
npm install -g @google/generative-ai-cli
```

## Usage

```bash
# Full debate
python main.py "Build a crypto dashboard with BTC/ETH prices and Polymarket events"

# With target project directory (enables file artifact writes)
python main.py "Build a real-time chat app" --project-path /path/to/project

# Quiet mode (suppress per-agent output)
python main.py "Build a SaaS invoicing app" --quiet

# Continue after human review (write spec.md + tasks.md)
python main.py "..." --mode continue --project-path /path --output report.md

# Single agent, single task
python main.py "..." --mode agent --agent architect --task write_tasks_md --project-path /path

# Headless + JSON output (scripting)
python main.py "..." --headless --format json

# Skip CodeReviewer gate
python main.py "..." --skip-review
```

## Output

Each run saves a markdown report:

- **Executive Summary**
- **Recommended Tech Stack** (with reasoning)
- **Architecture Overview** (with diagrams)
- **Key Risks & Mitigations**
- **Implementation Phases** (with milestones)
- **Open Questions**

Reports are auto-named: `report_build_a_crypto_20240315_143022.md`

## Project Bootstrapping

After a satisfactory plan is generated, bootstrap a clean project structure:

```bash
./create_project.sh <your-new-project-name>

# Custom output location
export PROJECTS_DIR=/path/to/your/projects
./create_project.sh <your-new-project-name>
```

## Configuration (`config.yaml`)

```yaml
defaults:
  backend: claude
  model: claude-sonnet-4-6
  temperature: 0.7

agents:
  planner:
    temperature: 0.5      # deterministic for JSON selection output
  skeptic:
    temperature: 0.9      # creative challenges
  code_reviewer:
    temperature: 0.3      # deterministic PASS/WARN/FAIL

  # Mix backends per agent
  researcher:
    backend: gemini
    model: gemini-2.0-flash

backends:
  claude:
    command: /path/to/claude
    args: ["--print", "--permission-mode", "bypassPermissions"]
  gemini:
    command: gemini
    args: ["-m", "{model}", "--yolo"]

debate:
  max_rounds: 2
  min_agents: 3
  max_agents: 5

cli_timeout_s: 120
```

## Testing

```bash
# Full regression suite (exception hierarchy, context store, CLI parsing, binary check)
pytest tests/regression_suite.py -v

# CLAUDECODE environment stripping audit
pytest tests/test_env_stripping.py -v

# All tests
pytest tests/ -v

# Skills token linter (≤200 tokens per SKILL.md)
python scripts/lint_skills.py

# With coverage
pip install pytest-cov
pytest tests/ --cov=. --cov-report=term-missing
```

| Test Suite | Covers |
|------------|--------|
| `regression_suite.py` | Exception hierarchy, ContextStore concurrency (500-item 10-thread), CLI JSON parsing + cache summing, binary validation |
| `test_env_stripping.py` | `CLAUDECODE` absent from every `subprocess.run()` call, including retries |
| `test_validator.py` | Empty/short/malformed JSON/mismatched `<write_file>` tags/truncation patterns |
| `test_rate_limiter.py` | Token bucket drain/refill, per-backend isolation, thread safety |
| `test_context_store.py` | Scalar get/set, list append, snapshot isolation, concurrent correctness |

## Module Map

```
main.py              CLI entry point, argument parsing, mode dispatch
orchestrator.py      Debate flow: selection → rounds → compression → synthesis → artifact gate
agents.py            Agent dataclass, factory functions, LLM backend dispatch
backends/
  cli_session.py     subprocess wrapper, --resume logic, CLAUDECODE stripping
  session_store.py   CLICallResult dataclass, session UUID persistence (.mas/sessions.json)
context_store.py     RLock-protected shared debate state (ContextStore)
exceptions.py        MASError hierarchy (BinaryNotFoundError, SessionError, PipelineError, ...)
validator.py         Response quality checks
rate_limiter.py      Per-backend token bucket rate limiting
health_check.py      Startup/deployment verification
skills/              Per-agent SKILL.md behavioral constraints (≤200 tokens each)
scripts/
  lint_skills.py     CI token cap enforcement (tiktoken cl100k_base)
```

## Troubleshooting

**`BinaryNotFoundError` at startup** — Install the configured CLI backend (see Installation). Binary is validated at `Orchestrator.__init__`, not lazily.

**Agents timing out** — Increase `cli_timeout_s` in `config.yaml` (default: 120s), or switch to a faster model.

**`CLAUDECODE` nested session error** — This is handled automatically. All subprocess calls strip the `CLAUDECODE` env var. If you see this error, check that you're running via `main.py` and not calling `CLISession` directly without `_get_env()`.

**Poor agent selection** — Lower the Planner's temperature to 0.3 in `config.yaml`. The Planner outputs JSON; high temperature causes parse failures.

**Rate limit errors** — Reduce `rpm` values in `config.yaml` under `rate_limiter`, or add delays between sessions.

**Previous session integrity warning** — A prior session log is missing `end_time`, indicating the process was killed mid-run. This is a warning only; the new session proceeds normally.
