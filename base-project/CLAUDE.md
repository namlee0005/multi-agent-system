# Project Rules

This file defines how Claude agents operate in this project. Read it first, every time.

## Startup Sequence

Every agent must follow this order when starting a new task:

1. **Read this file** (`CLAUDE.md`) — understand the rules
2. **Read `memory/context.md`** if it exists — understand current project state
3. **Read `spec.md`** if the task involves requirements or design
4. **Read `tasks.md`** before implementing anything
5. **Read `memory/progress.md`** to know what's already done

## Agent Roles

| Agent | Skill | Responsibility |
|-------|-------|---------------|
| Planner | `/planner` | Orchestrate agents, manage flow, synthesize outputs |
| Researcher | `/researcher` | Research tech stacks, best practices, options |
| Architect | `/architect` | Design system, produce tasks.md |
| Developer | `/developer` | Implement code in src/ |
| Reviewer | `/reviewer` | Validate code against spec.md |

### How to invoke a skill

Use the Skill tool with the skill name:
- `/planner` — start here for a new project
- `/researcher` — research a topic or tech decision
- `/architect` — design the system and create tasks
- `/developer` — implement code from tasks.md
- `/reviewer` — review the code in src/

## File Responsibilities

| File | Written by | Read by |
|------|-----------|---------|
| `spec.md` | Researcher, Architect | All agents |
| `tasks.md` | Architect | Developer, Reviewer |
| `src/` | Developer | Reviewer |
| `memory/progress.md` | Developer, Reviewer | All agents |
| `memory/decisions.md` | Architect, Planner | All agents |
| `memory/debate.md` | Planner | Planner |
| `memory/context.md` | Any agent | All agents |

## After Every Task

Agents must:
- Mark completed tasks in `tasks.md` with `[x]`
- Append a progress entry to `memory/progress.md`
- Log non-obvious decisions to `memory/decisions.md`

## Code Conventions

- Write clean, readable code — clarity over cleverness
- Functions should do one thing
- Handle errors explicitly — never silently swallow exceptions
- No unused code or dead imports
- **Comments in Vietnamese are fine** — write them if it helps clarity
- Follow the conventions of the chosen language/framework
- No hardcoded secrets — use environment variables

## Project Structure

```
.
├── CLAUDE.md           # This file — always read first
├── spec.md             # Requirements + tech stack + architecture
├── tasks.md            # Implementation plan with phases
├── src/                # All source code
│   └── tests/          # Tests live here
└── memory/
    ├── context.md      # Current project context
    ├── progress.md     # Task progress log
    ├── decisions.md    # Decision log
    └── debate.md       # Agent debate logs
```

## Important Rules

- **Never start coding without reading spec.md and tasks.md**
- **Never delete memory/ files** — they are the project's history
- **One task at a time** — complete and mark done before starting next
- **When in doubt, ask** — don't make assumptions about requirements
- If spec.md or tasks.md don't exist yet, run `/planner` first
