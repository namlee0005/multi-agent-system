# Multi-Agent Project Advisor Report

**Project:** Test project

## Selected Specialist Agents
1. **Researcher**
2. **Architect**
3. **Backend_Dev**
4. **Skeptic**

## Debate Round 1: Initial Proposals
### Researcher
My analysis focuses on identifying key patterns and potential improvements for the "Test project" multi-agent system. The current directory structure suggests a Python-based multi-agent architecture with a separate orchestration layer and a TypeScript component, possibly for communication or UI.

### Key Observations & Inferences:

1.  **Python-centric Agent System:** The presence of `agents.py` and `orchestrator.py` strongly indicates a Python backend for agent logic and coordination. This aligns with the popularity of Python in AI/ML and agent development due to its rich ecosystem (e.g., LangChain, CrewAI, AutoGen).
2.  **Explicit Orchestration:** `orchestrator.py` suggests a deliberate approach to managing agent interactions, which is a best practice for complex multi-agent systems to ensure coherent task execution and prevent chaotic behavior.
3.  **Configuration Management:** `config.yaml` points to externalized configuration, allowing flexibility without code changes, another good practice.
4.  **TypeScript Component (`base-project/src/socket.ts`):** This is a critical observation. The `.ts` extension implies a TypeScript file, and `socket` suggests WebSocket communication. This component likely handles real-time interaction, either as a client-side interface (e.g., a web UI interacting with the Python backend) or as a separate service for inter-agent communication.
5.  **Memory/Logging (`memory/decisions.md`, `logs/cli_calls.log`):** The project incorporates mechanisms for logging and decision-making records. This is crucial for debugging, auditing, and future training/improvement of agent behaviors.

### Recommendations:

1.  **Standardize Agent Framework (or Build a Robust Custom One):**
    *   **Recommendation:** Leverage existing, mature multi-agent frameworks like **LangChain** or **CrewAI** if the project's scope aligns with their abstractions. LangChain provides excellent tools for agent chaining, memory, and tool integration, while CrewAI focuses specifically on orchestrating "crews" of agents. This reduces boilerplate and provides battle-tested components.
    *   **Evidence:** LangChain has over 80k stars on GitHub, a vibrant community, and extensive integrations. CrewAI, though newer, is gaining rapid traction (e.g., companies like **Cognition Labs** are exploring similar modular AI approaches).
    *   **Anti-pattern to avoid:** Reinventing fundamental agent components (memory, tool invocation, prompt templating) unless the project has unique, prohibitive requirements that off-the-shelf frameworks cannot meet. This often leads to slower development and increased maintenance burden.

2.  **Define Communication Protocol & Patterns:**
    *   **Recommendation:** Clearly define how agents communicate with the orchestrator, and with each other (if direct communication is allowed). Given `socket.ts`, **WebSockets** are likely already in use. Ensure a robust message passing standard (e.g., JSON-RPC, Protobuf over WebSocket) for structured messages, error handling, and state synchronization.
    *   **Evidence:** Projects like **OpenAI's Assistant API** demonstrate a clear request-response model for tool use, while decentralized agent systems (e.g., in robotics) often rely on message brokers (like **Apache Kafka** or **RabbitMQ**) or peer-to-peer WebSocket connections for distributed coordination.
    *   **Anti-pattern to avoid:** Ad-hoc communication without a defined schema. This leads to brittle systems that are hard to scale, debug, and evolve.

3.  **Implement Robust Monitoring & Observability:**
    *   **Recommendation:** Expand logging and memory capture to include agent-specific metrics, prompt/response pairs, tool usage, and decision paths. Integrate with tools like **Prometheus/Grafana** for real-time monitoring of agent health, latency, and task completion rates.
    *   **Evidence:** **Google's SRE principles** heavily emphasize observability. In agent systems, this is critical for understanding "why" an agent made a particular decision, especially during failures or unexpected behaviors.
    *   **Anti-pattern to avoid:** "Black-box" agents where internal reasoning is not logged. This makes debugging complex multi-step failures nearly impossible.

4.  **Version Control for Prompts & Configurations:**
    *   **Recommendation:** Treat prompts and `config.yaml` as code. Store them under version control, and consider a system for A/B testing or rolling out prompt changes systematically.
    *   **Evidence:** Companies like **Mistral AI** and **Anthropic** emphasize the iterative nature of prompt engineering. Versioning is essential for reproducibility and rollback.

By adopting these recommendations, the "Test project" can build a more scalable, maintainable, and observable multi-agent system, leveraging established patterns from both the broader software engineering and emerging AI agent communities.
```

### Architect
## Architectural Analysis — Multi-Agent Project Advisor

**Current State:** The system is a well-structured orchestrator-of-agents pattern. `spec.md` is empty, so I'm analyzing the existing codebase to generate a meaningful `tasks.md`.

---

### System Architecture (Current)

```
CLI / User
    │
    ▼
Orchestrator
    ├── Planner (agent selection + synthesis)
    │
    ├── ThreadPoolExecutor (fan-out)
    │   ├── Researcher    ──► subprocess(gemini CLI) ──► stdout
    │   ├── Architect     ──► subprocess(claude CLI) ──► stdout
    │   ├── BackendDev    ──► subprocess(claude CLI) ──► stdout
    │   ├── DevOps        ──► subprocess(claude CLI) ──► stdout
    │   └── Skeptic       ──► subprocess(gemini CLI) ──► stdout
    │
    └── Planner (synthesis)
            │
            ▼
    logs/session-{id}.json
    logs/cli_calls.log
    base-project/tasks.md  (via <write_file> tag)
```

### Key Architectural Risks

1. **No retry logic** — any agent failure aborts its contribution silently
2. **Subprocess coupling** — tightly coupled to CLI tool availability; no abstraction over API vs CLI
3. **Single-threaded log writes** — `_log_lock` serializes all console I/O, potential bottleneck
4. **No context size management** — `previous_proposals` passed raw to all agents; large debates will hit token limits
5. **No persistent state** — session restartability is zero; failure mid-debate loses all work

### Recommended Improvements (Prioritized)

**High value, low risk:**
- Add retry with exponential backoff per agent call
- Truncate/summarize `previous_proposals` before injection to avoid token blowout
- Add a `--dry-run` mode that validates config without calling LLMs

**Medium term:**
- Abstract LLM backend into a proper interface (not subprocess-only)
- Add streaming output support so users see agent responses as they arrive

---



---

**Architecture verdict:** The current monolithic orchestrator is the right call for this project size — no microservices needed. The subprocess-to-CLI pattern is pragmatic but fragile; the highest-leverage investment is the `LLMBackend` abstraction (T3.x) which eliminates the CLI dependency risk. Prioritize Phase 1 first — reliability before features.

### Backenddev
## Backend Recommendations

### Language & Framework: **Python + FastAPI**

For this project, FastAPI is the clear choice:

- **Async-native** — `async/await` throughout, critical for any I/O-bound workload
- **Auto-generated OpenAPI docs** — zero extra effort, teams stay in sync
- **Pydantic v2** — runtime validation and serialization baked in; catches bad data at the boundary, not deep in business logic
- **Performance** — on par with Node.js/Go for typical CRUD-heavy workloads; overhead only matters at scale you're not at yet

Avoid Django for a new project: it's opinionated in ways that fight you once you leave the happy path. Flask is fine but you're writing boilerplate FastAPI gives you for free.

---

### Database: **PostgreSQL (primary) + Redis (cache/queues)**

- **Postgres** for all persistent data. JSONB columns handle schema flexibility without surrendering query power. Use `asyncpg` + `SQLAlchemy 2.0` async for the ORM layer — migration tooling (Alembic) is mature and well-understood
- **Redis** for caching hot reads, session state, and rate limit counters. Also doubles as a task queue broker if you need background jobs (via Celery or ARQ)
- Skip MongoDB unless you have a genuine document-store use case — Postgres JSONB covers 90% of that need with better consistency guarantees

---

### API Design: **REST**

- GraphQL adds resolver complexity and N+1 query risk that's hard to tame early
- gRPC is ideal for internal microservice comms but overkill for a primary API
- REST with versioning (`/api/v1/`) is predictable, cacheable, and tooling is universal

Use `PATCH` (not `PUT`) for partial updates. Return consistent error envelopes:
```json
{"error": {"code": "NOT_FOUND", "message": "...", "details": {}}}
```

---

### Real-Time: **Server-Sent Events (SSE) first, WebSockets if needed**

SSE covers 80% of real-time needs (notifications, live feeds, progress updates) with far simpler infrastructure — no connection state to manage, works over HTTP/2, automatic reconnect built into browsers. Upgrade to WebSockets only when you need bidirectional low-latency comms.

---

### Rate Limiting & Caching

- **Rate limiting**: Redis sliding window via `slowapi` (FastAPI middleware) — per-user limits on writes, looser on reads
- **HTTP caching**: `Cache-Control` headers + `ETag` on stable resources; Redis for computed/aggregated responses with TTL proportional to data freshness requirements
- **Background jobs**: ARQ (async Redis Queue) over Celery — simpler, async-native, no separate worker process manager needed for moderate job volumes

---

### Critical Non-Negotiables

1. **`DATABASE_URL` and all secrets via environment variables** — no exceptions, no hardcoding
2. **Database migrations checked into version control** (Alembic) — treat schema changes like code changes
3. **Structured logging** (`structlog`) from day one — JSON logs are searchable; plain text logs are archaeology

### Skeptic
# Skeptic's Analysis — Round 1

## What Is This, Actually?

This is a system that spawns multiple LLM agents via **subprocess CLI calls** to conduct a "debate" and synthesize project advice. Let's be honest about what we're looking at before we celebrate it.

---

## Core Architectural Concerns

### 1. Subprocess-as-API is an anti-pattern waiting to hurt you

```python
result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600)
```

You're shelling out to `claude` and `gemini` CLIs and parsing their stdout. This is:
- **Fragile**: CLI output formats change without notice, breaking your parser silently
- **Unversioned**: There's no lockfile for CLI tool versions — `gemini` updates and your parsing breaks at 2am
- **Unobservable**: Error handling is `returncode != 0` against stderr strings. Good luck distinguishing rate limits from auth failures from model errors

**Why not just use the official Python SDKs?** `anthropic` and `google-generativeai` are pip-installable, have typed responses, retry logic, and structured error types. The CLI approach buys you nothing except fragility.

### 2. The "debate" metaphor is load-bearing but undefined

You have a Skeptic, Architect, BackendDev, Security agent — but what is the **resolution mechanism**? If Security says "never do X" and BackendDev says "X is required", who wins? Synthesis by yet another LLM call is just **expensive coin-flipping with extra steps**.

Real design reviews work because humans have accountability and context. LLM agents have neither.

### 3. 8 agents × Opus 4.6 = your bill, not your insight

The config assigns `claude-opus-4-6` to Architect, BackendDev, FrontendDev, DevOps, and Security. Opus is the most expensive Claude model. A single debate run on a non-trivial project could cost **$10-50+ per invocation**. Is the output 10x better than Sonnet? Almost certainly not.

### 4. `bypassPermissions` is a red flag

```yaml
args: ["--print", "--permission-mode", "bypassPermissions"]
```

You're running Claude Code with `bypassPermissions` in an automated pipeline. This means any agent that proposes or executes file writes, shell commands, or code runs does so with **no human checkpoint**. This is how you get an "automation upgrade" that deletes your repo.

---

## What's Missing Entirely

- **No determinism**: Same project description → different advice every run. How do you know if the system is improving?
- **No evaluation**: There's no ground truth. How do you know when a debate produces good recommendations vs. confident-sounding hallucinations?
- **No cost controls**: No token budgets, no caching of repeated context

---

## The Honest Question

Could a single well-prompted Sonnet call — with a structured output schema — produce comparable results at 1/20th the cost and complexity? Almost certainly yes for 80% of use cases. **Prove that it can't before building an 8-agent orchestra.**

## Debate Round 2: Critiques & Refinements
### Researcher
## Researcher — Round 2 Challenge: Foundational Flaws Undermine Architectural Choices

My previous analysis focused on best practices for scaling and maintaining multi-agent systems. However, after reviewing the Architect's, BackendDev's, and especially the Skeptic's proposals, it's clear that the project faces fundamental architectural challenges that must be addressed *before* optimizing specific backend technologies or framework choices.

### Endorsing the Skeptic's Critique: Fragility and Cost are Project Killers

The Skeptic's points resonate deeply with real-world project failures and critical anti-patterns in system design:

1.  **Subprocess-as-API is an Extreme Anti-Pattern:** The reliance on shelling out to CLIs (`subprocess.run`) for LLM interaction is a severe technical debt. In production systems, such brittle integrations are a primary source of unforeseen outages and maintenance nightmares. CLI output formats *will* change, silently breaking parsers. Observability is crippled, making debugging a forensic exercise rather than a diagnostic one. Real-world projects, particularly those integrating third-party services, overwhelmingly adopt official SDKs for stability, type safety, structured error handling, and built-in features like retries and rate limiting. Ignoring mature Python SDKs for Anthropic and Google Gemini for a `subprocess` call is a decision that often leads to project abandonment due to accumulated fragility.
2.  **Unsustainable Cost Profile:** The default use of `claude-opus-4-6` for five agents (and implicitly, potentially more calls if a debate is iterative) is financially unsustainable for any non-trivial project. Opus is a premium model, and its cost impact must be justified by a proportionate increase in output quality that *cannot* be achieved by cheaper models like Sonnet or Haiku. Without clear metrics and evaluation (which are currently missing, as the Skeptic points out), defaulting to the most expensive option is an anti-pattern in resource management. Many real-world AI projects struggle with scaling costs; this setup is designed for rapid burn.

### Reinforcing Architect's Risks: Subprocess Coupling is a Critical Flaw

The Architect correctly identified "Subprocess coupling" as a key risk. This isn't just about elegant code; it's about system reliability and future adaptability. The Skeptic’s detailed explanation of the fragility of CLI parsing further underscores why the Architect's proposed `LLMBackend` abstraction is the single most critical near-term architectural improvement. Without it, any discussion of robust communication protocols or backend frameworks is moot.

### Contextualizing BackendDev's Recommendations

BackendDev's recommendations (FastAPI, PostgreSQL, Redis, REST, SSE) are generally sound and reflect industry best practices for modern web services. However, their immediate relevance is secondary to fixing the foundational agent communication layer. A beautiful FastAPI backend cannot compensate for a multi-agent system that is brittle, unobservable, and prohibitively expensive at its core. These choices are excellent *once the core agent interaction model is made stable, observable, and cost-effective*.

### Conclusion: Prioritize Stability, Cost-Efficiency, and Observability

Before contemplating advanced features or optimizing backend frameworks, this project must solidify its foundation. The immediate priorities, based on real-world evidence and avoiding common pitfalls, are:

*   **Replace `subprocess.run` with official LLM SDKs:** This dramatically improves stability, error handling, and observability.
*   **Implement robust cost controls and model selection strategy:** Justify high-cost models with demonstrable performance gains, or default to cost-effective alternatives.
*   **Establish evaluation metrics and determinism:** Without knowing if the system is producing *good* advice consistently, its value is entirely speculative.

A reliable, observable, and cost-conscious system, even if simpler initially, will succeed where a complex, fragile, and expensive one will fail.

### Architect
## Architect — Round 2 Challenge Response

The Skeptic landed three real hits. Let me be specific about which concerns are architectural risks vs. operational preferences, and where the prior proposals are wrong.

---

### Where the Skeptic is Correct (and Round 1 Underweighted These)

**1. Subprocess-as-API is a first-class architectural defect, not just fragility.**

The Researcher cited LangChain as a reference but never connected it to the actual pain point: the system has zero contract with its LLM backends. When `gemini` CLI updates its output format (not *if*), `_parse_agent_selection` silently returns garbage and falls back to defaults. You won't know. The session log will show `status: success`.

The fix is concrete and bounded — an `LLMBackend` protocol:

```
LLMBackend (Protocol)
├── AnthropicSDKBackend   ← pip install anthropic
├── GeminiSDKBackend      ← pip install google-generativeai
└── CLIBackend            ← current behavior, kept for dev convenience
```

One interface, three implementations. This is a 2–3 day task that eliminates the entire class of silent parse failures.

**2. `bypassPermissions` is not an operational concern — it's an architectural boundary violation.**

The BackendDev correctly identified structured logging and secrets management as non-negotiables. The same principle applies here: automated pipelines must not have unrestricted file system and shell access. The architecture needs a constraint: agents that *produce text recommendations* run with read-only permissions. Only the Planner's file-write step runs in a scoped write context targeting `project_path` only.

**3. The synthesis step has no resolution semantics.**

The Skeptic asked "who wins when agents conflict?" — the current `_synthesize()` call passes all proposals to another LLM with the instruction to "resolve disagreements." This is undefined behavior dressed as architecture. The fix: the Planner's synthesis prompt should use a structured conflict resolution schema — explicit `decision`, `rationale`, and `dissent` fields per topic — so the output is auditable, not just confident-sounding prose.

---

### Where the Skeptic Overshoots

**"Could a single Sonnet call produce comparable results?"** — Maybe for simple projects. But the value here isn't the individual outputs; it's the *adversarial structure*. A single LLM call won't spontaneously say "this is over-engineered" or "your cost model is wrong." The Skeptic agent exists precisely because self-critique in a single prompt is weak. The multi-agent overhead is justified *if* the Skeptic role is well-prompted and the synthesis actually incorporates dissent (which currently it doesn't — see above).

**Cost concerns are real but misdirected.** The solution isn't fewer agents — it's smarter model assignment. The current config assigns `claude-opus-4-6` to Architect, BackendDev, FrontendDev, DevOps, and Security. Sonnet 4.6 is sufficient for all specialist roles. Opus adds marginal quality at 5× cost. Reserve Opus for synthesis only.

---

Now generating `tasks.md`:



---

**Summary of Round 2 position:**

The Skeptic correctly identified the three highest-leverage risks: subprocess fragility (T1.1), `bypassPermissions` scope (T1.4), and undefined synthesis resolution (T1.5). The BackendDev's FastAPI/Postgres recommendation is reasonable but premature — this system has no HTTP surface yet, so those choices are hypothetical. The monolithic orchestrator remains the right architecture; the work is hardening what exists, not splitting services.

`tasks.md` written above with Phase 1 tasks ordered by risk, not effort.

### Backenddev
## Backend Dev — Round 2: Challenge

### The Skeptic Is Right About SDKs. Full Stop.

I'll eat my own words from Round 1: the subprocess approach I implicitly accepted without challenging is indefensible. The Skeptic nailed it. Here's the concrete fix:

```python
# Replace subprocess.run(["claude", "--print", ...]) with:
import anthropic
client = anthropic.Anthropic()
message = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=4096,
    messages=[{"role": "user", "content": prompt}]
)
```

Typed responses. Structured errors. Retry logic built in. Zero stdout parsing. This is a one-afternoon refactor that eliminates the single biggest fragility in the system.

---

### On the Cost Concern — The Skeptic Undersells the Problem

Opus 4.6 for every agent isn't just expensive — it's architecturally naive. Different agents have **different cognitive load requirements**:

| Agent | Required Capability | Right Model |
|-------|-------------------|-------------|
| Researcher | Retrieval + summarization | `gemini-2.0-flash` or Haiku |
| Skeptic | Pattern matching + critique | Sonnet |
| Architect | Reasoning + synthesis | Sonnet |
| Planner (final synthesis) | Complex reasoning | Opus if anywhere |

Opus where Sonnet suffices isn't "using the best tool" — it's leaving money on the table with no measurable quality gain. The Architect's LLM abstraction (T3.x) enables this differentiation cleanly.

---

### Challenge to the Architect: The Abstraction Is Underspecified

The proposed `LLMBackend` interface is the right call, but the Architect didn't define what it needs to handle. From a backend perspective, the interface must cover:

1. **Streaming** — users shouldn't wait 60s for a silent response; SSE out from the orchestrator endpoint
2. **Structured output enforcement** — agents that return free-form text create downstream parsing debt; the interface should enforce `response_format=json_schema` where the SDK supports it
3. **Per-call cost tracking** — input/output tokens must be logged per agent call, not just total; you can't optimize what you can't measure

---

### The `bypassPermissions` Issue Is a Backend Problem Too

The Skeptic flagged this as a security concern. I'll add the backend angle: this is also a **data integrity problem**. Agents writing files without checkpoints means no transactional semantics — a half-written `tasks.md` on crash is worse than no file at all. 

Fix: buffer all `<write_file>` outputs in memory during the debate, validate them post-synthesis, then write atomically via `tempfile` + `os.replace()`. One line of protection against partial writes.

---

### Where I Disagree With the Skeptic

"A single Sonnet call produces comparable results" — maybe for simple projects. The multi-agent debate catches contradictions (Security vs. BackendDev tension is *real* design signal) that self-consistency in a single prompt doesn't surface. The architecture is worth keeping. The *implementation* needs the fixes above.

### Skeptic
# Skeptic — Round 2: Still Not Convinced

## The Researcher's Framework Recommendations Are Cargo Culting

> "Leverage existing, mature multi-agent frameworks like LangChain or CrewAI"

This advice is backwards for this project. LangChain is notorious for over-abstraction — you end up debugging three layers of wrappers to understand why a prompt got mangled. The system here **already works** as a direct subprocess orchestrator. Swapping to LangChain doesn't fix the subprocess fragility problem I raised in Round 1; it just adds a dependency that changes its API every minor version.

CrewAI has ~35k GitHub stars and was founded in 2023. "Rapid traction" is not the same as production-proven. Cognition Labs is not a reference customer — they built their own stack.

**The actual recommendation should be:** migrate to the Anthropic and Google Python SDKs directly. That's one sentence of advice, not a framework migration.

## The Architect Identified the Right Risks Then Punted

> "Abstract LLM backend into a proper interface (not subprocess-only)"

Agreed — but the proposed `LLMBackend` abstraction in T3.x is still vague. "Abstraction" is not a solution. What does the interface look like? What error contract does it expose? Without that specificity, a developer implements it as a thin subprocess wrapper anyway and calls it done. The risk survives under a new name.

## BackendDev Is Answering the Wrong Question

The entire FastAPI + PostgreSQL + Redis stack recommendation assumes this system needs a **web backend**. Does it? The current codebase is a CLI tool that spawns agents. There is no API surface, no user authentication, no persistent data model worth a full ORM.

> "PostgreSQL (primary) + Redis (cache/queues)"

For what data? Agent stdout? That's a log file. This is a classic case of recommending the stack you know rather than the stack the problem needs. A `SQLite` file and `asyncio.Queue` covers 100% of the demonstrated requirements with zero operational overhead.

## The Unresolved Meta-Problem

My Round 1 question was not answered by anyone: **what is the resolution mechanism when agents disagree?**

The Architect noted "no context size management" as a risk but didn't address the deeper issue: the synthesis step is a single LLM call reading all agent outputs and producing a `tasks.md`. That's not synthesis — it's summarization. The "debate" framing implies adversarial refinement toward truth, but there's no iteration, no agent can update its position based on another's argument, and the final arbiter has no more ground truth than the participants.

**This is the most important unfixed flaw in the design.** Everything else is implementation detail.

## One Genuine Concession

BackendDev is right about SSE over WebSockets for the `socket.ts` component — if that component ever gets built out. That's the only recommendation in the batch that's both specific and correctly scoped to actual demonstrated need.

## Final Synthesis & Architecture Recommendation
# Final Project Recommendation: Multi-Agent System

## 1. Executive Summary

This project aims to use a "debate" of specialized LLM agents to generate high-quality project plans. The current proof-of-concept is functional but built on a fragile and costly foundation. The primary risks are the use of brittle CLI subprocess calls for LLM interaction, an unsustainable cost model defaulting to the most expensive models, and an undefined process for resolving agent disagreements.

The final recommendation is to **harden the existing orchestrator before adding new features.** This involves replacing CLI calls with direct SDKs, implementing strategic cost controls, and defining a structured synthesis process to ensure reliability and meaningful output.

## 2. Recommended Tech Stack

| Component | Recommendation | Reasoning |
| :--- | :--- | :--- |
| **Language** | **Python** | The project's current language. The AI/ML ecosystem (including required SDKs) is most mature in Python. |
| **LLM Interaction** | **Direct Python SDKs** (`anthropic`, `google-generativeai`) | **(Unanimous Agreement)** This is the most critical change, replacing fragile, unobservable `subprocess` calls. It provides stability, typed errors, and version safety. |
| **Orchestration** | **Existing Custom Monolith** | The current single-orchestrator pattern is sufficient. Migrating to a framework like LangChain or CrewAI would add unnecessary abstraction and complexity at this stage. |
| **Data Storage** | **SQLite** | The system is a CLI tool, not a web service. SQLite provides sufficient local persistence for logging and caching without the operational overhead of a full client-server database like PostgreSQL. |

## 3. Architecture Overview

The core architecture remains a monolithic orchestrator that manages the agent lifecycle. The key architectural change is introducing an `LLMBackend` abstraction layer to decouple the orchestrator from the LLM implementation.

```
Orchestrator (`orchestrator.py`)
    │
    ├─ 1. Selects Agents (Planner)
    │
    ├─ 2. Fans out prompts to Agents via `LLMBackend`
    │   │
    │   └─ LLMBackend (Interface)
    │      ├─ AnthropicSDKBackend (Claude)
    │      └─ GeminiSDKBackend (Gemini)
    │
    ├─ 3. Gathers structured responses
    │
    └─ 4. Synthesizes final plan with conflict resolution (Planner)
           │
           └─ Outputs (tasks.md, spec.md)
```

This design fixes the primary fragility (subprocess coupling) while retaining the simplicity of the existing monolithic structure.

## 4. Key Risks & Mitigations

| Risk | Mitigation |
| :--- | :--- |
| **Fragile Subprocess-as-API** | **Implement the `LLMBackend` abstraction** to use official Python SDKs. This provides stability, error handling, and observability. |
| **Unsustainable Cost** | **Implement strategic, per-agent model selection.** Use cost-effective models (e.g., Sonnet, Haiku) for most roles; reserve expensive models (Opus) only for the final, complex synthesis step. |
| **Undefined Conflict Resolution** | **Redesign the synthesis prompt.** Mandate a structured output that forces the Planner agent to explicitly identify conflicts and document its `decision`, `rationale`, and `dissenting_opinions`. |
| **Unrestricted File/Shell Access** | **Enforce a read-only context for agents.** File writes must only be performed by the orchestrator after the final plan is synthesized and validated, using an atomic write process to prevent partial file corruption. |

## 5. Implementation Phases

### Phase 1: Harden the Core
*   **1.1:** Implement the `LLMBackend` abstraction and replace all `subprocess` calls with SDKs.
*   **1.2:** Refactor the configuration to allow per-agent model selection and set cost-effective defaults.
*   **1.3:** Implement structured logging for per-agent token usage to enable cost tracking.
*   **1.4:** Remove `bypassPermissions` and implement a read-only agent execution context with a final, atomic file-write step.

### Phase 2: Improve Synthesis & Observability
*   **2.1:** Implement the structured conflict resolution prompt for the synthesis step.
*   **2.2:** Add result caching to provide determinism for identical inputs.
*   **2.3:** Begin basic state management with SQLite for logging debate history.

### Phase 3: Feature & Evaluation
*   **3.1:** Explore iterative debates where agents can respond to each other's arguments.
*   **3.2:** Develop a formal evaluation framework to score the quality of generated advice.

## 6. Open Questions & Next Steps

*   **Defining "Good" Advice:** The biggest open question is how to quantitatively measure the quality of the system's output. A formal evaluation framework (Phase 3) is critical for long-term improvement.
*   **Debate vs. RFC:** Is an adversarial "debate" the best model? A more collaborative "Request for Comment" (RFC) structure might yield better results and should be explored after the core is stabilized.

**Immediate Next Step:** Begin Phase 1, starting with the `LLMBackend` implementation. This single task delivers the highest-leverage improvement to the project's stability and maintainability.
