# Multi-Agent Project Advisor

A debate-driven technical advisory system where specialized AI agents discuss and challenge each other to produce well-reasoned project recommendations.

## How It Works

```
User Request
    ↓
Planner analyzes → selects 3-5 relevant agents
    ↓
Round 1: Each agent proposes their perspective
    ↓
Round 2: Agents challenge/support each other's proposals
    ↓
Planner synthesizes → Final recommendation (saved as markdown)
```

## Agents

| Agent | Role |
|-------|------|
| **Planner** | Moderator — selects agents, synthesizes final output |
| **Researcher** | Best practices, similar projects, evidence-based evaluation |
| **Architect** | System design, scalability, patterns |
| **BackendDev** | Backend stack, APIs, databases, real-time data |
| **FrontendDev** | UI frameworks, state management, charts/viz |
| **DevOps** | Deployment, infra, CI/CD, monitoring |
| **Security** | Threat modeling, auth, vulnerabilities |
| **Skeptic** | Devil's advocate — challenges all proposals |

## Installation

```bash
pip install pyyaml
```

You also need at least one LLM backend CLI installed:

```bash
# Option A: Claude CLI (recommended)
npm install -g @anthropic-ai/claude-code
# or: pip install claude-cli

# Option B: Gemini CLI
npm install -g @google/generative-ai-cli

# Option C: OpenAI CLI
pip install openai
```

## Usage

```bash
# Basic usage
python main.py "Build a crypto dashboard with BTC/ETH prices and Polymarket events"

# With custom output file
python main.py "Build a real-time chat app" --output chat_report.md

# Quiet mode (suppress per-agent output, show summary only)
python main.py "Build a SaaS invoicing app" --quiet

# Custom config
python main.py "Build an ML pipeline" --config my_config.yaml

# Don't save to file
python main.py "Build a blog" --no-save
```

## Output

Each run saves a markdown report with:
- **Executive Summary**
- **Recommended Tech Stack** (with reasoning)
- **Architecture Overview** (with diagrams)
- **Key Risks & Mitigations**
- **Implementation Phases** (with milestones)
- **Open Questions**

Reports are auto-named: `report_build_a_crypto_20240315_143022.md`

## Configuration (`config.yaml`)

```yaml
defaults:
  backend: claude        # claude | gemini | openai
  model: claude-sonnet-4-6
  temperature: 0.7

agents:
  planner:
    backend: claude
    model: claude-sonnet-4-6
    temperature: 0.5    # Lower = more deterministic

  skeptic:
    backend: claude
    model: claude-sonnet-4-6
    temperature: 0.9    # Higher = more creative challenges

# Mix backends per agent
  researcher:
    backend: gemini
    model: gemini-2.0-flash

  architect:
    backend: openai
    model: gpt-4o
```

### Supported Backends

| Backend | CLI Command | Notes |
|---------|-------------|-------|
| `claude` | `claude --print` | Input via stdin |
| `gemini` | `gemini --yolo` | Input via stdin |
| `openai` | `openai api chat.completions.create` | Input via stdin |

## Examples

### Crypto Dashboard
```bash
python main.py "Build a crypto dashboard with BTC/ETH prices and Polymarket events"
```

### SaaS App
```bash
python main.py "Build a B2B invoicing SaaS with multi-tenant support, Stripe billing, and PDF generation"
```

### ML System
```bash
python main.py "Build an ML pipeline for real-time fraud detection processing 10k transactions/second"
```

### Game Backend
```bash
python main.py "Build a real-time multiplayer game server for a 2D battle royale with 100 players per match"
```

## Architecture

```
main.py          CLI entry point, argument parsing, report saving
orchestrator.py  Debate flow: agent selection → rounds → synthesis
agents.py        Agent class definitions, LLM backend calls
config.yaml      Model assignments, backend configuration
```

The `Orchestrator` maintains a shared `context` dict that grows as debate progresses. Each agent receives:
- The project description
- Previous agents' proposals (in round 2)
- Their specialized system prompt

## Troubleshooting

**"Backend command not found"**: Install the relevant CLI tool (see Installation above).

**Agents timing out**: Increase the timeout in `agents.py` (`timeout=120`), or switch to a faster model.

**Poor agent selection**: The Planner couldn't parse its own JSON output. Edit `config.yaml` to lower the Planner's temperature to 0.3.

**Rate limit errors**: Add `time.sleep(2)` between agent calls in `orchestrator.py:_run_round()`.
