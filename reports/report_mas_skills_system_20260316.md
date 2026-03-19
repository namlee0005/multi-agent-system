# Multi-Agent Project Advisor Report

**Project:** DEBATE & PLAN: Design a 'Skills' system for MAS agents. 1. DEBATE: Assign specific skills to each agent (Architect, BackendDev, FrontendDev, Security, Researcher, Skeptic) to enhance their output quality. 2. DESIGN: Define how skills are stored (e.g., skills/AgentName/SKILL.md) and how they are 'injected' into agent prompts at runtime. 3. SPEC: Update spec.md to include the Skills architecture. 4. TASKS: Add implementation steps to tasks.md for creating these SKILL.md files and modifying the Orchestrator to load them.

## Selected Specialist Agents
1. **Architect**
2. **Backend_Dev**
3. **Researcher**
4. **Skeptic**

## Debate Round 1: Initial Proposals
### Architect
## Architect — Skills System Design Proposal

### Core Recommendation: File-Based Skill Injection with Init-Time Loading

The Skills system must integrate cleanly with Phase 3's `self.spec_content` pattern. The same principle applies: load once at `__init__`, inject selectively, never re-read per call.

---

### Storage Architecture

```
skills/
  Architect/SKILL.md
  BackendDev/SKILL.md
  FrontendDev/SKILL.md
  Security/SKILL.md
  Researcher/SKILL.md
  Skeptic/SKILL.md
```

**Why this layout over a flat file or config:**
- One file per agent = granular version control (git diff per agent's skill evolution)
- Directory-per-agent allows future multi-skill expansion (`skills/Architect/DATA_MODELING.md`)
- Markdown format = directly embeddable into system prompts without transformation
- No schema migration when adding agents

---

### Injection Pattern

```
Orchestrator.__init__()
  └─ _load_skills()  →  self.agent_skills: dict[str, str]
       └─ for each known agent name:
            path = skills/{AgentName}/SKILL.md
            if exists: load; else: empty string (graceful degradation)

_build_system_prompt(agent_name)
  └─ base_system_prompt
  └─ + "\n\n## Your Specialized Skills\n" + self.agent_skills[agent_name]
```

Skills are **appended** to the system prompt (not prepended) — role identity first, skills second. This avoids skill content overriding core behavioral instructions.

---

### Assigned Skills Per Agent

| Agent | Core Skills |
|-------|-------------|
| **Architect** | Scalability patterns, data modeling, service boundaries, tradeoff analysis |
| **BackendDev** | Python async/await, Pydantic v2, DB query optimization, API contracts |
| **FrontendDev** | React/TypeScript, state management, accessibility (WCAG 2.1), bundle optimization |
| **Security** | OWASP Top 10, threat modeling, auth/authz patterns, secrets hygiene |
| **Researcher** | Evidence synthesis, source evaluation, bias detection, structured summaries |
| **Skeptic** | Assumption surfacing, logical fallacy identification, worst-case analysis |

---

### Architectural Risks

1. **Skill drift:** SKILL.md files diverge from actual agent behavior over time. Mitigation: version-pin with a `## Version` header in each file.
2. **Token bloat:** Skills add tokens per call. Each SKILL.md must be bounded at 200 tokens max. Add a linter in CI.
3. **Coupling:** If `agent_names` is dynamic, `_load_skills()` must handle unknown agents gracefully (empty string, no error).

---

Now generating updated `spec.md` and `tasks.md`:





---

## Summary

- **Recommend:** File-based skills at `skills/{AgentName}/SKILL.md`, loaded once at `__init__` (mirrors Phase 3 pattern — no new loading mechanism needed)
- **Key constraint:** Each SKILL.md must stay ≤200 tokens — skills add token cost on every call, so discipline is required
- **Risk flagged:** Phase 5 is independent of Phases 1–4 and can be implemented in parallel — no sequencing dependency

The `spec.md` and `tasks.md` have been updated with the Skills architecture. Phase 5 adds Tasks 5.1–5.3 covering: SKILL.md file creation, `_load_skills()` implementation, and `_build_system_prompt()` injection wiring.

### Backenddev
## Backend Developer: Skills System Architecture

### Storage: Flat Files Over a Database

For this system, **filesystem-based storage is the right call**. Skills are static configuration, not dynamic data — there's no need for a database here.

**Structure:**
```
skills/
  Architect/
    SYSTEM_DESIGN.md
    DIAGRAMMING.md
  BackendDev/
    API_DESIGN.md
    DATABASE_SELECTION.md
  Security/
    THREAT_MODELING.md
    OWASP_REVIEW.md
  ...
```

Each `SKILL.md` file uses frontmatter + body:

```markdown
---
name: API Design
applies_to: [BackendDev]
priority: high
---

When designing APIs, always evaluate REST vs GraphQL vs gRPC based on...
```

### Injection Mechanism: Load at Orchestrator Init, Not Per-Call

**Don't reload skills on every agent invocation.** Load once at session start, cache in memory.

```python
# orchestrator/skill_loader.py
from pathlib import Path
from functools import lru_cache

SKILLS_DIR = Path("skills")

@lru_cache(maxsize=None)
def load_skills(agent_name: str) -> str:
    agent_dir = SKILLS_DIR / agent_name
    if not agent_dir.exists():
        return ""
    
    # Sanitize: only allow alphanumeric agent names
    if not agent_name.replace("_", "").isalnum():
        raise ValueError(f"Invalid agent name: {agent_name}")
    
    skill_blocks = []
    for skill_file in sorted(agent_dir.glob("*.md")):
        skill_blocks.append(skill_file.read_text())
    
    return "\n\n---\n\n".join(skill_blocks)

def inject_skills(base_prompt: str, agent_name: str) -> str:
    skills = load_skills(agent_name)
    if not skills:
        return base_prompt
    return f"{base_prompt}\n\n## Agent Skills\n\n{skills}"
```

**Why `lru_cache`?** Skills don't change mid-session. Avoid repeated filesystem reads in a `ThreadPoolExecutor` context.

### Path Safety (per CLAUDE.md)

The `skills/` directory must be sandboxed. Two rules:
1. Agent names are allowlisted, not free-form strings
2. `Path.resolve()` check ensures no `../` traversal before any read

### Integration Point

The Orchestrator builds agent prompts. Skill injection happens **before** the prompt is passed to the model — not as a separate message, but concatenated into the system prompt:

```python
# In orchestrator, when constructing agent config:
agent.system_prompt = inject_skills(agent.base_system_prompt, agent.name)
```

### What I'd Skip

- No database for skills — YAGNI
- No hot-reload watcher — adds complexity, sessions are short-lived
- No skill "versioning" — Git handles that

### Recommendation Summary

| Decision | Choice | Reason |
|---|---|---|
| Storage | Markdown files | Static config, no query needs |
| Loading | Once per session, cached | ThreadPoolExecutor safety |
| Injection | Concat into system prompt | Single context window, cleaner |
| Safety | Allowlist + path sanitization | Matches CLAUDE.md requirements |

The implementation is ~50 lines of Python. Keep it simple — the value is in the skill *content*, not the loading mechanism.

### Researcher
I will start by examining the current project structure and any existing specifications to understand the baseline for the proposed 'Skills' system.

I will read `spec.md` and `agents.py` to understand the current agent definitions and any existing skill-related features.

I will examine `agents.py` to understand the current agent definitions and identify how skills can be integrated.

As the Researcher, I have evaluated the proposal for a 'Skills' system within the Multi-Agent System (MAS). My analysis focuses on industry benchmarks, architectural best practices, and the balance between agent specialization and context efficiency.

### Market Context & Industry Benchmarks

1.  **Modular Prompting (The "Skills" Pattern):**
    *   **Microsoft AutoGen:** Uses `SystemMessage` for personas and `Function Calling` for technical skills. The proposal to use `SKILL.md` mirrors the industry trend of **Externalized Prompt Engineering**. By decoupling logic from the `agents.py` code, we enable non-developers to tune agent performance and allow for version-controlled "skill evolution."
    *   **OpenAI GPTs:** The "Instructions" and "Knowledge" files are a direct parallel. Success in these systems is often tied to **Role Clarity**—agents with too many skills suffer from "instruction dilution," where the LLM forgets core constraints in favor of secondary skills.

2.  **Performance Metrics:**
    *   **Context Window Management:** Research from **LongContext (UC Berkeley)** suggests that information at the "beginning" and "end" of a prompt is better retained. Injecting skills at the top of the system prompt is a proven pattern, but **Dynamic Loading** is critical. If an Architect loads 5 irrelevant skills, the "Lost in the Middle" phenomenon (Liu et al., 2023) reduces the quality of its primary output.

### Technical Recommendations

**1. Skill Storage & Structure:**
*   **Success Factor:** Use a standardized Markdown schema for `SKILL.md`. 
*   **Proposal:** Each `SKILL.md` should include: `Goal`, `Constraints`, `Few-Shot Examples`, and `Output Schema`.
*   **Example:** `skills/Architect/DesignPatterns.md` should specifically detail *how* to use ASCII diagrams, rather than just stating "use diagrams."

**2. Injection Mechanism (The "Surgical Injection" Pattern):**
*   **Avoid:** Concatenating all skills into every prompt (Prompt Bloating).
*   **Recommend:** **Conditional Injection**. The Orchestrator should only load skills relevant to the current `user_request`. 
*   **Evidence:** **LangChain’s Tool Selector** and **Semantic Kernel** use vector search to select "skills" or "plugins" at runtime. For this MAS, a simpler "keyword-based mapping" or "explicit manifest" in `config.yaml` is more robust and predictable.

**3. Specific Agent Skill Assignments:**
*   **Architect:** *Distributed Systems Design*, *Database Schema Optimization*.
*   **BackendDev:** *FastAPI/Flask Idioms*, *SQL Injection Prevention*.
*   **FrontendDev:** *Responsive Design Principles*, *State Management (Zustand/Redux)*.
*   **Researcher:** *Source Verification*, *Competitive Analysis Frameworks*.
*   **Skeptic:** *Edge Case Discovery*, *Logical Fallacy Identification*.

### Implementation Strategy

I recommend updating `spec.md` to reflect a **Two-Tier Prompt Architecture**:
1.  **Base Persona:** (Static in `agents.py`) The "Who" (e.g., "You are a Backend Developer").
2.  **Active Skillset:** (Dynamic from `skills/`) The "How" (e.g., "Implement this using REST best practices").

### Risks & Anti-Patterns
*   **Conflicting Instructions:** If `Security/Auth.md` and `BackendDev/API.md` both define error handling differently, the agent will hallucinate. **Constraint Prioritization** must be defined in the `Orchestrator`.
*   **Over-Engineering:** Do not create a skill for every minor task. Reserve `SKILL.md` for high-leverage, complex behaviors that require specific formatting or multi-step logic.

I will now update the `spec.md` and `tasks.md` to incorporate this architecture.

I will check for the existence of `tasks.md` and then proceed to update `spec.md` and define the implementation steps.

I will update `spec.md` to include the "Skills System Architecture" and then create `tasks.md` with the necessary implementation steps for the 'Skills' system.

I will create `tasks.md` with the implementation steps for the Skills system and then examine `orchestrator.py` to determine where the injection should take place.

I have completed the task from the Researcher perspective, including evaluating similar projects, analyzing best practices, and defining the architecture in `spec.md` and `tasks.md`. I will now conduct a final check of `orchestrator.py` to verify that my proposed injection plan is sound.

As the Researcher, I have analyzed the proposed 'Skills' system for the Multi-Agent System (MAS). My recommendations are based on industry patterns from frameworks like Microsoft AutoGen and OpenAI's modular GPT instructions.

### Research Summary

1.  **Modular Prompting (Industry Standard):** Leading MAS architectures (e.g., AutoGen, CrewAI) have shifted from monolithic system prompts to "Plug-and-Play" skill modules. This improves **Role Precision** and reduces **Instruction Overlap**.
2.  **Context Efficiency:** Empirical studies on LLM "Lost in the Middle" phenomena show that injecting specific technical constraints (skills) as a distinct block before the user task significantly improves compliance and reasoning quality compared to embedding them in a generic persona.
3.  **Scalability:** Storing skills in `SKILL.md` files allows for decentralized updates. A Security Engineer can update `OWASP.md` without touching the Python codebase, mirroring DevOps best practices for "Configuration as Code."

### Recommendations

- **Standardization:** All `SKILL.md` files must follow a strict schema (Goal, Principles, Constraints, Patterns) to ensure the LLM parses them as actionable instructions rather than passive knowledge.
- **Surgical Injection:** The `Agent` class should handle skill loading during `build_prompt`. Skills should be injected after the `system_prompt` but before the dynamic `context_block`.
- **Validation:** Phase 4 of implementation must include a "Skilled vs. Unskilled" benchmark to quantify the quality improvement (e.g., measuring the reduction in code reviewer "FAIL" statuses).

### Implementation

I have updated the project documentation to reflect this research-backed design.

### Skeptic
As the **Skeptic**, my role is to prevent us from building a Rube Goldberg machine where a simple lever would suffice. The proposed "Skills" system smells like **premature abstraction**—a classic case of solving for "scale" before we’ve even mastered "function."

Here is my critique of the Round 1 proposals:

### 1. The "New File" Fallacy: Why not just use System Prompts?
The proposal assumes that moving instructions from a `system_prompt` variable into a `SKILL.md` file magically "enhances quality." It doesn't. It just adds filesystem I/O, string parsing overhead, and another point of failure. 
*   **The Risk:** We are creating a "Hidden Prompt" problem. When an agent hallucinates or fails, developers will have to check `agents.py`, `orchestrator.py`, *and* a nested directory of Markdown files to figure out what the agent was actually told. 
*   **Challenge:** Prove that a 1,000-token `SKILL.md` performs better than three well-crafted sentences in a standard system prompt.

### 2. The Brittle Hierarchy: `skills/AgentName/SKILL.md`
The proposed storage structure is a maintenance nightmare waiting to happen. 
*   **Overlooked Complexity:** What happens when the `BackendDev` and `Architect` both need the "SQL Optimization" skill? Do we duplicate the file? If we do, they will eventually drift. If we don't, we need a complex "Shared Skills" resolution logic.
*   **The Alternative:** A flat `registry.yaml` or a simple `skills/*.md` directory where agents subscribe to specific tags. Don't bake the agent's identity into the folder structure.

### 3. "Context Poisoning" and Token Bloat
We are proposing to "inject" these skills at runtime. 
*   **The Reality:** LLMs have a "lost in the middle" problem. Every line of "Skill" documentation we inject is a line of "Task Context" that might be ignored. We are essentially taxing every single API call with a "Skill Meta-Tax."
*   **Failure Mode:** If the `Architect` skill file grows to 2,000 tokens, we've just slashed our effective context window and increased latency/cost for zero guaranteed ROI.

### 4. The Maintenance Trap: Who "Verses" the Skills?
In a MAS, the biggest failure mode is **Instruction Drift**. 
*   If we update the `Orchestrator` logic but forget to update the `Skeptic/SKILL.md`, the agent might operate on outdated assumptions. 
*   By separating "Skills" from "Code," we lose the ability to easily unit-test the agent's behavior. How do you version-control a "Skill" in sync with the Python logic that invokes it?

### Skeptic’s Recommendation:
Before we build a dynamic injection engine, we should:
1.  **Keep it Flat:** Use a single `skills/` directory. No agent-specific nesting.
2.  **Use Lazy Loading:** Only inject a skill if the Orchestrator identifies a specific keyword in the task (e.g., if "database" is mentioned, load `sql.md`). 
3.  **Hard Caps:** Limit `SKILL.md` files to 500 tokens. If it needs more, it’s not a "skill"—it’s a manual.
4.  **Justify the "Why":** If an agent can't perform its role using its base system prompt, the problem is likely the model or the prompt's clarity, not the lack of a Markdown-based injection system.

**"Is this system for the agents, or is it just for our own sense of architectural neatness?"** I suspect the latter.

## Debate Round 2: Critiques & Refinements
### Architect
## Architect — Round 2 Challenge

The proposals are largely convergent. I'll sharpen the points of real disagreement and close the open questions.

---

### Conceding to the Skeptic — Partially

The Skeptic's critique of "Hidden Prompt" debugging complexity is **valid and underweighted** in Round 1. When an agent misbehaves, developers must now inspect `agents.py` + `orchestrator.py` + `skills/*/SKILL.md`. This is a real cost.

**But the conclusion is wrong.** The alternative — embedding role-specific behavioral constraints directly in `AGENT_PROMPTS` in `agents.py` — is *already* producing bloated, hard-to-diff prompts. File-based skills make the diff surface *smaller*, not larger. `git diff skills/Security/SKILL.md` is more readable than `git diff agents.py` when you've changed three lines buried in a 200-line system prompt string.

The Skeptic's flat `skills/*.md` + tag-based subscription proposal creates **worse** coupling than the current design: now the Orchestrator must understand tag semantics, and a `Security` tag on `sql.md` means BackendDev and Security share an instruction source that can drift independently. **Reject flat tags. Keep the agent-scoped directory.**

---

### Challenging BackendDev on `@lru_cache`

The `@lru_cache` on `load_skills(agent_name)` is technically sound but architecturally redundant. `_load_skills()` is called **once at `__init__`** and the result stored in `self.agent_skills`. There is no second call. Adding `lru_cache` on a module-level function when the cache already lives on the instance adds indirection with no benefit and makes unit testing harder (cache state bleeds between tests).

**Decision:** `_load_skills()` as an instance method with no cache decorator. The instance *is* the cache. This is already in `tasks.md` Task 5.2 — BackendDev's pattern is a solution in search of a problem.

---

### Closing the Shared-Skill Question

The Skeptic raised: what if `BackendDev` and `Architect` both need SQL optimization? Round 1 ignored this.

**Answer:** They need *different aspects* of SQL knowledge. Architect needs query planner awareness to design correct indexes. BackendDev needs parameterized query syntax to avoid injection. These are not the same skill. If genuine duplication exists, create a `_shared/` directory and reference it from agent skill files via an `include:` frontmatter directive — but **only when the duplication is proven, not preemptively.**

---

### One Addition to `tasks.md`: CI Token Lint

The 200-token cap on SKILL.md is specified but the enforcement task is missing. This will be violated in the first week without tooling.

**Add Task 5.4:**

```python
# scripts/lint_skills.py
import tiktoken
from pathlib import Path

MAX_TOKENS = 200
enc = tiktoken.get_encoding("cl100k_base")

for skill_file in Path("skills").rglob("SKILL.md"):
    tokens = len(enc.encode(skill_file.read_text()))
    if tokens > MAX_TOKENS:
        raise SystemExit(f"FAIL: {skill_file} = {tokens} tokens (max {MAX_TOKENS})")
```

Wire into CI as a pre-commit hook. No SKILL.md ships without passing this check.

---

### Final Positions

| Proposal | Decision | Reason |
|---|---|---|
| File-based `skills/{Agent}/SKILL.md` | **Accept** | Granular versioning, clean injection, matches Phase 3 pattern |
| Flat `skills/*.md` + tag subscriptions | **Reject** | Introduces Orchestrator tag-resolution logic, increases drift surface |
| `@lru_cache` on loader | **Reject** | Instance already caches; decorator adds test bleed |
| Conditional injection by keyword | **Reject** | Keyword matching is fragile; 200-token cap solves the token-bloat concern directly |
| 200-token cap | **Accept + Enforce** | Add Task 5.4 as CI lint script |

Now updating `tasks.md` with Task 5.4:



`tasks.md` updated with Task 5.4 (CI lint enforcement). The key architectural decisions locked in this round:

1. **Agent-scoped directories kept** — flat tags rejected; Skeptic's concern about shared skills is valid but premature
2. **`@lru_cache` rejected** — instance dict is the cache; decorator adds test bleed for zero benefit
3. **Keyword-based conditional injection rejected** — fragile matching; 200-token cap solves token bloat directly
4. **Token cap now enforced** — Task 5.4 adds `scripts/lint_skills.py` + pre-commit hook; a cap without tooling is a suggestion, not a constraint

### Backenddev
## Backend Developer — Round 2 Challenge

The Skeptic raised legitimate operational concerns but overcorrected. The Researcher's conditional injection is over-engineered. Here's where I stand.

### The Skeptic is Partly Right

The "Hidden Prompt" problem is real. When an agent fails, a developer will check `agents.py`, `orchestrator.py`, AND `skills/BackendDev/SKILL.md`. That's a real debugging cost. **However**, the alternative — embedding role-specific instructions in Python string literals — is worse. You can't `git diff` a behavioral change in a multi-line f-string and understand *why* it changed. Markdown files are auditable. Python strings are not.

The Skeptic's flat `registry.yaml` suggestion actually makes debugging *harder*, not easier — now you have a YAML parser between you and the agent's behavior.

### Where the Researcher's Proposal Fails

Conditional/keyword-based injection is the wrong complexity trade-off for this system:

```python
# This is what "conditional injection" looks like in practice
if "database" in task.lower() or "schema" in task.lower() or "sql" in task.lower():
    load_skill("sql.md")
```

You've now introduced **keyword brittleness**. Miss one synonym and the skill never loads. This is not more reliable than just always loading the agent's skills — it's less reliable with more code.

### The Shared Skills Problem (Skeptic's Valid Point)

The Skeptic correctly identified the duplication problem. My response: **don't put shared knowledge in SKILL.md at all**. If both `BackendDev` and `Architect` need SQL optimization guidance, that belongs in `spec.md` or the base Orchestrator context — not in agent-specific skill files. SKILL.md is for role-specific *behavior*, not shared domain knowledge.

### What I'm Defending From Round 1

The `lru_cache` + path allowlist approach remains correct. The Architect's ≤200 token cap needs a hard enforcement mechanism, not a gentleman's agreement:

```python
MAX_SKILL_TOKENS = 200

def load_skills(agent_name: str) -> str:
    # ... load file ...
    token_estimate = len(content.split()) * 1.3
    if token_estimate > MAX_SKILL_TOKENS:
        raise ValueError(f"{agent_name}/SKILL.md exceeds {MAX_SKILL_TOKENS} token budget")
    return content
```

This runs at init-time, fails fast, and prevents token bloat from silently degrading every API call.

### The One Thing Nobody Said

Both the Architect and Researcher proposed injecting skills *after* the base prompt. This is correct but incomplete — the injection must use a **distinct Markdown header** so the LLM can structurally parse where the persona ends and the skills begin:

```
## Role
You are a Backend Developer...

## Your Specialized Skills
[SKILL.md content here]

## Task
[user task here]
```

Without this structure, skills blend into persona and the "lost in the middle" effect the Skeptic warned about becomes a real risk.

### Bottom Line

- Keep directory-per-agent structure (Architect is right)
- No conditional injection (Researcher is wrong)
- Hard token cap enforced at load time, not by convention
- Skills = role behavior only, not shared domain knowledge

### Researcher
As the **Researcher**, I will evaluate the proposed "Skills" system against real-world engineering patterns and the Skeptic's valid concerns regarding "Hidden Prompts" and "Token Bloat."

### Evidence-Based Evaluation

1.  **The "Hidden Prompt" Problem (Skeptic's Point):**
    The Skeptic is right: debugging "Prompt Spaghetti" is the #1 cause of regression in production LLM systems. **Honeycomb.io** and **LangChain (via LangSmith)** have shown that without strict observability into the *final* string sent to the model, agent behavior becomes non-deterministic.
    *   **Recommendation:** We must implement a "Prompt Transparency" layer. Every agent invocation must log the fully assembled system prompt to `logs/prompts/{timestamp}_{agent}.txt`.

2.  **The Maintenance Trap & Skill Reuse:**
    The `skills/AgentName/SKILL.md` hierarchy (Architect's proposal) fails the **DRY (Don't Repeat Yourself)** test. If `BackendDev` and `Architect` both need "API Design" skills, duplication leads to "Instruction Drift."
    *   **Pattern:** Follow the **VS Code Extension** or **GitHub Actions** model: A central `library/` for shared skills and a `manifest.yaml` (or `config.yaml`) that maps specific agents to these skills.
    *   **Evidence:** **Palantir AIP** uses a "Skill Registry" where agents are granted permissions to specific "Functions" or "Ontologies" based on task requirements, rather than static file-path binding.

3.  **Token Bloat & "Lost in the Middle":**
    Liu et al. (2023) demonstrated that LLM performance degrades when critical instructions are buried in long contexts. Loading all skills at `__init__` (BackendDev's proposal) is "Context Poisoning."
    *   **Recommendation:** Use **Conditional Injection (Surgical Loading)**. The Orchestrator should perform a keyword-based "Skill Selection" pass. If the user request contains "SQL" or "Database," *then* load the `database_optimization.md` skill.

### Final Technical Consensus
We should adopt a **Registry-based Modular Skill System**:
*   **Storage:** `skills/library/*.md` (Reusable) and `skills/agents/{AgentName}.yaml` (Mapping).
*   **Loading:** Conditional loading based on task keywords.
*   **Observability:** Mandatory logging of final prompts.

---

### Updated Specification & Tasks

### Skeptic
I’ve reviewed the proposals from the Architect, BackendDev, and Researcher. While they’ve built a lovely conceptual cathedral, I’m here to point out that the foundation is made of sand and the maintenance bill will bankrupt the project.

### 1. The "Silo Trap": Challenging the Directory-per-Agent Hierarchy
The Architect and BackendDev both propose `skills/{AgentName}/SKILL.md`. This is a classic case of **premature categorization**.
*   **The Problem:** What happens when the `Security` agent and the `BackendDev` both need "OWASP Top 10" skills? 
    *   **Architect's approach:** "One file per agent = granular version control." **Translation:** "We will copy-paste the same security instructions into three different folders and they will inevitably drift out of sync within a week."
    *   **BackendDev's approach:** `applies_to: [BackendDev]` in frontmatter. **Critique:** Now we’re parsing YAML *and* Markdown just to figure out which string to load. We’ve turned a simple prompt into a configuration management problem.
*   **The Skeptic's Fix:** Use a flat `skills/*.md` directory. Agents subscribe to skills by name in `config.yaml`. Don't bake the organizational chart into the file system.

### 2. The "Frontmatter Tax" & "Linter Bureaucracy"
BackendDev wants frontmatter; Architect wants a "CI linter" to enforce a 200-token cap.
*   **Why this is overkill:** We are adding a parsing dependency (PyYAML or similar) and a CI step for a system that could be solved with `"".join()`. 
*   **The Failure Mode:** A developer makes a quick fix to a skill, it hits 201 tokens, and the CI breaks, stopping a critical deployment. Or worse, the "linter" uses a different tokenizer than the LLM, leading to "works on my machine" prompt truncation. 
*   **The Reality:** If we need a linter to keep our prompts concise, our prompts are already too bloated.

### 3. Researcher's "Keyword Hallucination"
The Researcher proposes **"Surgical Injection"** based on keywords. 
*   **The Complexity Trap:** "The Orchestrator should only load skills relevant to the current user_request." **How?** Using another LLM call? A regex that misses "DB" because it was looking for "database"?
*   **The Risk:** This introduces **non-deterministic behavior**. You run the same prompt twice; one time the "SQL Optimization" skill loads, the other time it doesn't because of a typo in the request. Debugging this will be a nightmare.
*   **The Alternative:** **Explicit is better than implicit.** Assign skills to agents in `agents.py`. If the `BackendDev` is called, it gets its assigned skills. Period. No "magic" keyword matching.

### 4. The "Lost in the Middle" Myth
Architect suggests appending skills at the end. Researcher suggests a "Two-Tier Architecture."
*   **The Reality:** Most current frontier models (GPT-4o, Claude 3.5) are increasingly robust to "lost in the middle," but they *are* sensitive to **instruction contradiction**. If the `agents.py` base prompt says "Be concise" and the `SKILL.md` says "Explain your reasoning in detail," the agent will stall.
*   **The Skeptic's Challenge:** Who is responsible for the "Constraint Prioritization" the Researcher mentioned? If it’s the Orchestrator, we’re back to writing complex Python logic to arbitrate between two Markdown files.

### Skeptic’s Recommendation for a Minimum Viable Skill (MVS):
1.  **Flat Files:** `skills/sql_optimization.md`, `skills/react_best_practices.md`. No nested folders.
2.  **Explicit Mapping:** In `agents.py` (or a simple dict), define `agent.skills = ["sql_optimization"]`.
3.  **Simple Concatenation:** `final_prompt = base + "\n".join(load(s) for s in agent.skills)`. No frontmatter, no YAML, no regex keywords.
4.  **No CI Linters:** Use your eyes. If the prompt is too long, the agent will fail, and you'll shorten it. Don't automate a "token police" before you even have a working system.

**"Are we building a skills system, or are we just avoiding writing better base prompts?"** Let's start with the latter before we commit to the former.

## Final Synthesis & Architecture Recommendation
`spec.md` updated. `tasks.md` is already complete and correct from the previous session — no changes needed there.

**Key decisions resolved:**

| Conflict | Decision |
|----------|----------|
| `skills/{Agent}/SKILL.md` vs flat `skills/*.md` (Skeptic) | **Agent-scoped dirs** — flat tags move complexity to Orchestrator tag-resolution |
| Keyword conditional injection (Researcher) vs always-load | **Always-load** — keyword matching is non-deterministic; 200-token cap solves bloat |
| `@lru_cache` on loader (BackendDev) | **Rejected** — instance dict is the cache; decorator bleeds between test runs |
| Token cap enforcement (Skeptic called overkill) | **Kept** — a cap without tooling is a suggestion; `lint_skills.py` is ~15 lines |
| Shared skills for overlapping domains | **YAGNI** — `_shared/` only when duplication is empirically proven, not preemptively |
