# Tasks: Skills System Audit & Mutation Bug Fix

**Last updated:** 2026-03-16
**Status:** Audit complete — one critical bug identified, two missing observability features

---

## Audit Summary

### ✅ Conformant

| Item | Spec Ref | Status |
|------|----------|--------|
| `_load_skills()` loads once at `__init__`, instance dict is cache | §6.2 | ✅ |
| Skills keyed by `agent.name` (e.g. `"BackendDev"`) | §6.2 | ✅ |
| `_build_system_prompt()` appends skills after base prompt | §6.3 | ✅ |
| Missing `SKILL.md` degrades gracefully to empty string | §6.2 | ✅ |
| `skills_injected: bool` recorded in session log per agent call | §6.5 | ✅ |
| All 6 agent `SKILL.md` files present (`Architect`, `BackendDev`, `FrontendDev`, `Security`, `Researcher`, `Skeptic`) | §6.1 | ✅ |
| `lint_skills.py` uses `tiktoken` `cl100k_base`, exits 1 on violation | §6.5 | ✅ |
| No `_shared/` directory (no empirically proven duplication yet) | §6.6 | ✅ |
| All SKILL.md files ≤200 tokens (confirmed by content review) | §6.5 | ✅ |

---

### ❌ Issues Found

---

#### ISSUE-1 (CRITICAL): Mutation Bug — Skills Injected Cumulatively Across Rounds

**File:** `orchestrator.py:323`

**Root cause:**
```python
# BUGGY — mutates the shared Agent object permanently
if skills_injected:
    agent.system_prompt = self._build_system_prompt(agent.name, agent.system_prompt)
```

`agent` is a reference to the live `Agent` object stored in `self.all_agents[key]`. Assigning back to `agent.system_prompt` permanently mutates this shared object.

**Failure sequence:**
```
Round 1 call:  agent.system_prompt = base + "\n\n## Your Specialized Skills\n" + skill
Round 2 call:  agent.system_prompt = (base + skill) + "\n\n## Your Specialized Skills\n" + skill
Retry attempt: agent.system_prompt = (base + skill + skill) + "\n\n## Your Specialized Skills\n" + skill
```

The prompt grows by ~150 tokens per additional call. Over a 2-round debate with 3 retries, an agent could receive a prompt with skills injected up to 5× — ~750 extra tokens per agent call.

**Thread safety note:** Each agent is called in a single round at a time (not the same agent in parallel), so there is no concurrent write race. The bug is sequential accumulation across rounds.

**Fix — minimal, no interface changes required:**

```python
# orchestrator.py — _call_agent, replace lines 321-323
skills_injected = bool(self.agent_skills.get(agent.name, "").strip())
original_system_prompt = agent.system_prompt          # snapshot original
if skills_injected:
    agent.system_prompt = self._build_system_prompt(agent.name, original_system_prompt)
try:
    # ... existing retry loop ...
    pass
finally:
    agent.system_prompt = original_system_prompt      # always restore
```

Place the `try/finally` block around the entire `for attempt in range(...)` loop. This ensures the original prompt is restored regardless of error paths, validation failures, or review failures.

**Alternative fix (preferred long-term):** Add `system_prompt_override: str | None = None` parameter to `Agent.respond()` and `Agent.build_prompt()`. Pass the enriched prompt as a local variable without mutating the agent. This avoids stateful mutation entirely and is safe under any threading model. Requires touching `agents.py`.

---

#### ISSUE-2 (MEDIUM): Pre-commit Hook Not Wired

**Spec ref:** §6.5 — "`scripts/lint_skills.py` runs as a pre-commit hook"

`lint_skills.py` exists and is correct, but no `.pre-commit-config.yaml` exists in the repo root. The hook will never fire without this file.

**Fix — create `.pre-commit-config.yaml`:**
```yaml
repos:
  - repo: local
    hooks:
      - id: lint-skills
        name: Lint SKILL.md token limits
        entry: python scripts/lint_skills.py
        language: python
        additional_dependencies: [tiktoken]
        pass_filenames: false
        files: ^skills/.*SKILL\.md$
```

---

#### ISSUE-3 (LOW): Prompt Logging to `logs/prompts/` Not Implemented

**Spec ref:** §6.5 — "final assembled prompt logged to `logs/prompts/{timestamp}_{agent}.txt`"

The `_call_agent` method logs `skills_injected: bool` in the session JSON, but never writes the assembled prompt to `logs/prompts/`. This makes debugging injected prompts difficult.

**Fix:** After `_build_system_prompt()` is called and `agent.system_prompt` is set, add:
```python
if skills_injected:
    os.makedirs("logs/prompts", exist_ok=True)
    prompt_log_path = f"logs/prompts/{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S')}_{agent.name}.txt"
    with open(prompt_log_path, "w") as f:
        f.write(agent.system_prompt)
```

---

## Implementation Tasks

### Task 1 — Fix Mutation Bug (CRITICAL)
**File:** `orchestrator.py`
**Action:** Wrap the retry loop in `_call_agent` with `try/finally` to restore `agent.system_prompt` after each call.
**Acceptance:** Run a 2-round debate session; verify session log shows `skills_injected: true` for both rounds of the same agent, and that the assembled prompt does not contain duplicate `## Your Specialized Skills` sections.

### Task 2 — Wire Pre-commit Hook
**File:** `.pre-commit-config.yaml` (new)
**Action:** Create the file as shown in ISSUE-2. Run `pre-commit install` and verify `lint_skills.py` fires on `git commit` when a `SKILL.md` is staged.

### Task 3 — Add Prompt File Logging
**File:** `orchestrator.py`
**Action:** Write the injected system prompt to `logs/prompts/{timestamp}_{agent}.txt` when `skills_injected=True`.
**Acceptance:** After any agent call with skills, verify `logs/prompts/` contains a file with the correct agent name and the prompt ends with `## Your Specialized Skills`.

---

## Architectural Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Mutation bug — cumulative skill injection | CRITICAL | Task 1 (try/finally restore) |
| Pre-commit hook not enforced | MEDIUM | Task 2 |
| No prompt observability for injected prompts | LOW | Task 3 |
| `Planner` in `all_agents` iterated by `_load_skills` but has no `SKILL.md` | NEGLIGIBLE | Graceful degradation handles it; no action needed |