# Multi-Agent Project Advisor Report

**Project:** Build a Python CLI Todo List Manager

## Selected Specialist Agents
1. **Architect**
2. **Backend_Dev**
3. **Skeptic**

## Debate Round 1: Initial Proposals
### Architect
## Architectural Analysis: Todo CLI Manager

### Architecture Decision: Layered Monolith

For a personal CLI todo manager, a **layered monolith** is the correct choice. No microservices, no event bus — complexity must be proportional to scope.

```
┌─────────────────────────────────────┐
│           CLI Layer (Typer)         │  ← Commands: add, list, complete, delete, search
├─────────────────────────────────────┤
│         Service Layer               │  ← Business logic, validation, filtering
├─────────────────────────────────────┤
│         Repository Layer            │  ← SQLite CRUD abstractions
├─────────────────────────────────────┤
│         Model Layer (Pydantic v2)   │  ← TaskModel, TagModel, data contracts
├─────────────────────────────────────┤
│         SQLite (via sqlite3)        │  ← Single .db file in ~/.config/todo-cli/
└─────────────────────────────────────┘
```

**Why SQLite over JSON:** ACID guarantees, free filtering/sorting via SQL, no full-file rewrites on every mutation. JSON is a footgun for concurrent writes (even from a single process with signals).

**Why sync over async:** This is a CLI tool — one user, one command at a time. Async I/O adds zero throughput benefit and considerable complexity. Keep it sync.

**Single Point of Failure:** The SQLite file. Mitigation: write to a temp file, then `os.replace()` for atomic schema migrations. WAL mode enabled by default.

---

Now generating `tasks.md`:



The `tasks.md` has been written to `todo-cli-project/tasks.md`.

**Architecture summary:**

- **Layered monolith** — CLI → Service → Repository → SQLite. Correct scope for a personal tool; microservices would be over-engineering by 3 layers.
- **Sync throughout** — no async needed; CLI is inherently single-request-at-a-time.
- **SQLite with WAL mode** — ACID writes, free SQL filtering, no JSON full-file rewrite on every mutation.
- **Pydantic v2 models** at every layer boundary — `TaskCreate`, `TaskUpdate`, `Task`, `FilterParams` enforce contracts between CLI args and DB operations.
- **Three-table schema** — `tasks`, `tags`, `task_tags` — normalized many-to-many so tag filtering is a clean `EXISTS` subquery, not a string-split hack.

Key risk flagged: SQLite `foreign_keys` pragma is **OFF by default** — must be explicitly enabled per connection or cascade deletes silently fail.

### Backenddev
## Backend Analysis: Python CLI Todo Manager

### Storage: SQLite with SQLModel (not raw SQLite)

Use **SQLite + SQLModel** (built on SQLAlchemy + Pydantic v2). Raw SQLite is fine for a toy; SQLModel gives you:
- Type-safe models shared between DB schema and CLI validation
- Migration path to Postgres if this ever becomes multi-user
- Pydantic v2 validators for free (due dates, priority enum enforcement)

Avoid JSON file storage. It breaks on concurrent writes, has no query capability, and `LIKE` searches require full-file reads.

**Schema sketch:**
```python
class Task(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(max_length=255)
    priority: Priority = Field(default=Priority.medium)  # Enum: low/medium/high/critical
    due_date: date | None = None
    completed_at: datetime | None = None  # timezone-aware, UTC
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tags: str = Field(default="")  # comma-separated; join table is overkill here
```

### CLI Framework: Typer over Click

**Typer** is the right call. It derives CLI args from Python type hints — no decorator boilerplate. With Pydantic v2 in the stack, the type-system consistency is valuable. Click requires manual `@click.option` declarations that duplicate your model fields.

### No async needed here

This is a CLI tool with local SQLite — there's no I/O concurrency. Don't introduce `asyncio` for its own sake. SQLite is synchronous by design and `aiosqlite` adds complexity with zero benefit in a single-user CLI. Keep it synchronous.

### Search/Filter: SQLite FTS5

For search, use **SQLite FTS5** (full-text search extension) rather than `WHERE title LIKE '%query%'`. It's built into Python's `sqlite3` module and handles multi-word queries correctly. Set up a virtual FTS table that mirrors the `tasks` table.

### DB Location & Path Safety

```python
DB_PATH = Path.home() / ".local" / "share" / "todo-cli" / "tasks.db"
DB_PATH = Path(os.path.realpath(DB_PATH))
assert str(DB_PATH).startswith(str(Path.home()))  # path traversal guard
```

Never accept a user-supplied DB path without `realpath()` sanitization.

### Data Integrity Rules

- `due_date` stored as ISO-8601 date string in SQLite (no naive datetimes)
- `priority` as a Python `IntEnum` so sorting works naturally: `ORDER BY priority DESC`
- Soft deletes only — add `deleted_at: datetime | None` and filter it out. Permanent delete is a separate `purge` command.

### Dependency summary

```
typer[all]       # CLI + Rich included
sqlmodel         # ORM + Pydantic v2 models  
rich             # output formatting (pulled in by typer[all])
```

No external services, no network calls, no async runtime. This stays simple and fast.

### Skeptic
## Skeptic Analysis: Python CLI Todo Manager

### Hidden Assumptions to Surface First

The spec assumes this needs to be "robust" and "beautiful." For a personal todo list, those words are warning signs. Let's pressure-test every major proposal.

---

### Challenge 1: SQLite is Overkill for a Todo List

> *"SQLite for storage"*

**Label: Advisory**

A personal todo list will have hundreds of items, not millions. SQLite introduces a dependency, a migration story, and a schema that must evolve. When you add a new field in month 3, you're writing `ALTER TABLE` statements.

**Simpler alternative:** A single `todos.json` file in `~/.config/todo/`. Human-readable, trivially debuggable, zero schema migration burden, and `cat todos.json` works as a backup strategy. If you hit performance problems with JSON at 10,000 items, that's a *good* problem—cross it when you reach it.

---

### Challenge 2: Rich + Typer Is Two Frameworks for One Script

> *"Typer or Click... Rich for beautiful terminal output"*

**Label: Advisory (escalates to blocking if team is small)**

Rich is 5MB of dependency. Typer wraps Click which wraps argparse. You now have three abstraction layers before your code runs. For a personal CLI tool, pretty tables are a luxury that adds upgrade surface and import time.

**Simpler alternative:** Click alone (or even argparse), with `print()` and simple string formatting. You can always add Rich later. Starting with it means you're optimizing the display layer before the data layer is proven.

---

### Challenge 3: "Categorization + Due Dates + Priority + Search" in Round 1

**Label: Blocking**

This is five features described in one bullet point as if they're trivial. Each one is a design decision:

- Do tags form a hierarchy or flat list?
- Are due dates stored as UTC or local time? (Daylight saving will bite you.)
- Is priority ordinal (1-5) or named (low/medium/high)? What happens when you sort mixed types?
- Does search match tags, titles, descriptions, or all three?

Shipping all of this in v1 guarantees none of it gets done well.

**Simpler alternative:** Ship v1 with add/list/complete/delete + JSON storage. Prove the data model works before bolting on five orthogonal features.

---

### The Real Risk Nobody Is Naming

The blast radius here isn't technical failure — it's abandonment. **This is a personal tool.** The graveyard of over-engineered personal CLI tools is vast. SQLite migrations you don't maintain, Rich formatting you never quite get right, a categorization system you added but never used.

**Worst case (likely):** The tool becomes too complex to modify casually, so you stop using it and go back to a notes app.

---

### Constructive Bottom Line

Build the simplest thing that captures tasks persistently. One file, one library, twenty lines of real logic. Then iterate based on *actual* friction, not anticipated friction.

## Debate Round 2: Critiques & Refinements
### Architect
## Architect — Round 2 Challenge

### Concession to Skeptic (partial, not full)

The Skeptic is right on **scope**. Shipping tags + due dates + priority + search + full Rich formatting in v1 is a recipe for an unfinished tool. I'll accept: **v1 ships add/list/complete/delete with priority and due date only.** Tags and search move to v2. This is a real concession, not a hedge.

The JSON argument, however, I reject. "Human-readable and trivially debuggable" is true until you run two terminal windows simultaneously, or a SIGKILL hits mid-write. WAL-mode SQLite is also human-inspectable (`sqlite3 tasks.db .dump`). The migration burden is one `ALTER TABLE` per new column — that's not a burden, that's a one-liner.

---

### Challenge to BackendDev: SQLModel is Wrong Here

BackendDev proposes SQLModel as an upgrade from raw `sqlite3`. This introduces **SQLAlchemy as a transitive dependency** — a library with 150k lines of code, designed for multi-database enterprise ORM use. For a single-file local SQLite tool this is not a "migration path," it's dead weight that will make startup time measurably slower and the dependency tree fragile.

**The raw `sqlite3` + Pydantic v2 split is correct.** Pydantic handles validation contracts; `sqlite3` handles persistence. These are different concerns and should stay separated. SQLModel's attempt to unify them creates a leaky abstraction: you end up fighting the ORM when you need raw SQL for anything non-trivial (window functions, CTEs, FTS5 queries).

---

### Challenge to BackendDev: Comma-Separated Tags is an Anti-Pattern

```python
tags: str = Field(default="")  # comma-separated; join table is overkill here
```

This is a genuine design error, not a simplification. Comma-separated fields in a relational DB violate 1NF. The consequences:

- `WHERE tags LIKE '%python%'` matches `python`, `cpython`, and `python3` — wrong.
- You cannot query "all tasks tagged X" without a full table scan with string matching.
- Tag rename requires string replacement across all rows.

A join table is **three lines of DDL and four lines of Python**. It is not overkill. It is the minimum correct solution.

---

### Accept from BackendDev: FTS5 for Search

FTS5 is already compiled into CPython's `sqlite3` module on all major platforms. Using it instead of `LIKE '%query%'` is zero additional dependency cost and handles tokenization correctly. This should be in the design.

```sql
CREATE VIRTUAL TABLE tasks_fts USING fts5(title, description, content=tasks, content_rowid=id);
```

---

### Revised Architecture Position

Keeping the layered monolith. Revising scope:

| Feature | v1 | v2 |
|---------|----|----|
| Add/list/complete/delete | ✓ | — |
| Priority + due date | ✓ | — |
| Tags (join table) | — | ✓ |
| FTS5 search | — | ✓ |
| Rich formatting | Minimal | Full |

Raw `sqlite3` + Pydantic v2 + Typer. No SQLModel, no aiosqlite, no ORM. The Skeptic's instinct about abandonment risk is correct — the mitigation is a smaller v1, not a simpler permanent architecture.

### Backenddev
## Backend Challenge: Responding to the Skeptic

### On SQLite Being "Overkill" — Disagree, but Partially

The Skeptic's JSON argument would land if this were a throwaway script. It doesn't land here because the spec explicitly requires **search and filter**. `WHERE priority = 'high' AND due_date < '2026-04-01' AND tags INCLUDE 'work'` is one SQL query. In JSON it's: read file → deserialize → loop → filter → sort. That's not premature optimization, it's using the right tool.

That said, the Skeptic is right that **SQLModel is the wrong choice**. I'm walking back my own Round 1 recommendation.

SQLModel is still immature (SQLAlchemy 2.x compatibility has been shaky), and for a single-table CLI tool, the ORM abstraction buys nothing. **Raw `sqlite3` from the stdlib with explicit SQL is better here** — no third-party ORM dependency, no magic, migrations are just `ALTER TABLE` strings you write once.

Revised dependency list:
```
typer[all]    # CLI + Rich (stdlib sqlite3 handles DB)
```

That's one dependency. The Skeptic wanted simplicity — this delivers it without sacrificing SQL's query capability.

### On Rich + Typer Being "Two Frameworks" — Reject

`typer[all]` installs Rich as a sub-dependency. You don't choose to add Rich; it comes along. The real question is whether to use it. For a todo list, `rich.table.Table` for `list` output is 5 lines of code and makes the tool actually usable vs. `print()` formatting that breaks on long titles. This is not premature optimization — it's the core UX of a CLI tool.

### On the Feature Scope — Partially Agree

The Skeptic is correct that shipping tags + due dates + priority + search in v1 is risky. But the right response isn't "ship less" — it's **sequence the schema correctly so you don't paint yourself into a corner**.

The three-table schema the Architect proposed (`tasks`, `tags`, `task_tags`) is the right schema even if you only implement `tasks` in v1. Adding a join table later to a production SQLite file with existing data is a migration nightmare. Design the schema for v1.5, ship the features for v1.

Concrete sequencing:
- **v1:** `add`, `list`, `complete`, `delete` + priority column (stored but not filtered)
- **v1.1:** due date filtering
- **v1.2:** tags via the join table that's already in the schema

### One Point Nobody Has Made

The Architect flagged `PRAGMA foreign_keys = ON` needing explicit enablement. This must be in the connection factory, not scattered across call sites:

```python
def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn
```

Forget this once and cascade deletes silently do nothing. Centralize it.

### Summary Position

- SQLite yes, SQLModel no — use stdlib `sqlite3`
- Rich yes, it's already there via Typer
- Full schema upfront, staged feature delivery
- One dependency total

### Skeptic
## Skeptic Round 2: Doubling Down and Targeting New Proposals

My Round 1 concerns stand. Now I have specific proposals to dissect.

---

### Challenge 1: The Repository Pattern for a CLI Tool

> *"CLI Layer → Service Layer → Repository Layer → Model Layer → SQLite"* — Architect

**Label: Blocking (over-engineering)**

That's four layers of abstraction for a program whose entire job is `INSERT INTO tasks`. The hidden assumption: this architecture will "pay off" as the tool grows. It won't — personal tools don't grow, they get abandoned or rewritten.

The Repository pattern exists to swap data sources (e.g., SQLite in dev, Postgres in prod). You will never swap this tool's data source. You're paying the abstraction tax with zero chance of collecting the dividend.

**Simpler alternative:** One `storage.py` file with five functions: `add_task`, `list_tasks`, `complete_task`, `delete_task`, `search_tasks`. Flat. Direct. Done in 80 lines.

---

### Challenge 2: SQLModel is the Wrong Bet

> *"Use SQLite + SQLModel... migration path to Postgres if this ever becomes multi-user"* — BackendDev

**Label: Advisory (bordering on blocking)**

"Migration path to Postgres" is the most dangerous phrase in software. It's a justification for complexity that will never be needed. This is a **personal CLI tool**. It will never be multi-user. If it somehow is, you'll rewrite it — the migration path from SQLModel to a real web app is not `ALTER TABLE`, it's a full architectural change anyway.

SQLModel is also a relatively thin project with a historically slow maintenance pace. You're adding a dependency for a problem you don't have.

**Simpler alternative:** Raw `sqlite3` (stdlib, zero dependencies) with a `schema.sql` file. You already know SQL. Write it directly.

---

### Challenge 3: FTS5 is Premature Optimization

> *"Use SQLite FTS5 (full-text search extension) rather than LIKE"* — BackendDev

**Label: Advisory**

FTS5 requires a virtual table, a trigger or manual sync to keep it current, and careful handling of tokenization edge cases. For a personal todo list where "search" means "find the task I added last Tuesday about the dentist," `WHERE title LIKE '%dentist%'` is correct. It is not slow. It is not broken. It handles 10,000 rows in under a millisecond.

**Simpler alternative:** `LIKE` with an index on `title`. Add FTS5 when a real user complains about search quality — which will never happen on a personal tool.

---

### The One Thing I'll Concede

The Architect is right about one thing: **no async**. The BackendDev proposal doesn't push async either, so this is consensus. Good. Async in a CLI is a genuine footgun — `asyncio.run()` wrapping every command entry point, stack traces through event loop internals on errors. Sync SQLite is the correct call.

---

### Net Verdict

Both proposals share the same failure mode: **building for a scale and team size that doesn't exist**. Four-layer architecture, ORM with migration path, FTS5 — each individually defensible on a team project, collectively disqualifying for a solo personal tool. The complexity budget is already spent before a single task is stored.

## Final Synthesis & Architecture Recommendation
# Python CLI Todo List Manager — Synthesis

## Executive Summary

Build a focused, maintainable CLI tool using a flat-but-structured architecture. The Skeptic's abandonment risk warning is the most important signal in this debate: complexity kills personal tools. The final design accepts SQLite (the Skeptic's JSON argument doesn't survive the search/filter requirement) but rejects every unnecessary abstraction layer.

---

## Recommended Tech Stack

| Choice | Decision | Reasoning |
|--------|----------|-----------|
| **Python 3.12+** | ✓ Keep | No debate |
| **Typer** | ✓ Keep | Type-hint-native CLI; Rich bundled via `typer[all]` |
| **Rich** | ✓ Keep | Already a transitive dep; `Table` output is the core UX |
| **SQLite (stdlib)** | ✓ Keep | SQL filtering is essential; ACID writes matter |
| **SQLModel / SQLAlchemy** | ✗ Reject | 150k LOC ORM for a single local file — never justified |
| **aiosqlite / async** | ✗ Reject | Zero throughput benefit; async in CLI is a footgun |
| **FTS5** | Defer to v2 | `LIKE` is fast enough at personal-tool scale |

**One production dependency:** `typer[all]`. Everything else is stdlib.

---

## Architecture Overview

```
CLI Layer (Typer commands)
    │
    ▼
storage.py  ←── Five flat functions, direct SQL, no repository pattern
    │
    ▼
SQLite (~/.local/share/todo-cli/tasks.db)
```

**Resolving the Architect vs. Skeptic layering debate:** The four-layer repository pattern is rejected. The Skeptic wins this point — you will never swap this tool's data source. `storage.py` with five direct functions is the correct scope. Pydantic v2 `TaskModel` lives in `models.py` for validation contracts; that's the only abstraction layer earned.

**Schema:** Three tables (`tasks`, `tags`, `task_tags`) defined upfront, features delivered incrementally. BackendDev and Architect agree here — designing schema for v1.5 while shipping v1 features avoids painful data migrations later.

**Connection factory** (centralized, non-negotiable):
```python
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn
```

---

## Key Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Abandonment from over-engineering | Hard v1 scope: 4 commands only |
| `PRAGMA foreign_keys` off by default | Centralized `get_conn()` — never scattered |
| Schema migration pain | Full 3-table schema in `schema.sql` from day one |
| Path traversal on DB location | `os.path.realpath()` + home dir assertion |

---

## Implementation Phases

**Phase 1 — Core (ship this):** `add`, `list`, `complete`, `delete` + priority column + due date storage. Single `tasks` table. Rich table output. Tests against real SQLite file (no mocks).

**Phase 2 — Tags:** Activate `tags`/`task_tags` tables. Add `--tag` filter to `list`. Tag commands: `tag add`, `tag remove`.

**Phase 3 — Search:** `LIKE`-based search first. Upgrade to FTS5 only if search quality proves inadequate (it won't).

---

## Open Questions

1. Should `complete` archive tasks or soft-delete them? (`completed_at` timestamp vs. `deleted_at`) — recommend soft-delete, `purge` command for cleanup.
2. Local time vs. UTC for due dates? Store UTC, display local — but pick this in Phase 1 or regret it.
3. Config file for DB path override? Keep it an env var (`TODO_CLI_DB`) — no config file needed in v1.
