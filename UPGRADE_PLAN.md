# MAS Functional Skills & Workflow Upgrade Plan (Inspirations from Deer-Flow)

**Date:** 2026-03-24  
**Strategy:** Pure CLI Implementation + Graph-Based Workflow  

---

## 1. Concept: Functional vs. Instructional Skills

The MAS system is evolving from **Instructional Skills** (static guidelines in `SKILL.md`) to include **Functional Skills** (executable tools like web search, file management, and ComfyUI interaction).

To comply with the requirement of **NOT using SDKs**, we will implement "Tool Use" via a pattern called **Interception & Resume**.

---

## 2. The Interception & Resume Pattern (Tool Use)

Since we are using the `claude` and `gemini` CLI tools, we will use a text-based protocol instead of native API function calling:

1.  **Emission:** The Agent emits a specific text marker when it needs a tool:  
    `[TOOL_CALL: tool_name | {"arg": "value"}]`
2.  **Interception:** The `Orchestrator` scans the CLI output for this marker.
3.  **Execution:** The `Orchestrator` executes the corresponding Python function locally.
4.  **Resume:** The `Orchestrator` re-invokes the CLI using the `--resume` flag:  
    `claude --resume [session_id] "[TOOL_RESULT: {"data": "..."}]"`
5.  **Completion:** The Agent processes the result and provides the final answer.

---

## 3. Workflow Evolution: From Linear to DAG (Inspired by Deer-Flow)

To improve efficiency and robustness, MAS will transition from a fixed linear process to a **Directed Acyclic Graph (DAG)**.

### 3.1 Conditional Execution (Early Exit)
- **Consensus Evaluator:** Between rounds, a new node will analyze agent agreement.
- **Skip Logic:** If agents reach a high consensus score (e.g., >85%), the system skips directly to the Synthesis phase, saving time and tokens.

### 3.2 Three-Layer State Management
We will replace the flat `ContextStore` with a structured `WorkflowState`:
- **Layer 1: Conversation State** (History of agent dialogues).
- **Layer 2: Task State** (Progress against the roadmap).
- **Layer 3: World State** (Facts retrieved via Functional Skills).

### 3.3 Recovery Routing
- Instead of simple retries, failed tasks are routed to a **Recovery Node**.
- This node analyzes the failure, simplifies the task, or provides more context for a retry.

---

## 4. Implementation Roadmap

### Phase 1: The Foundation (Week 1)
- Create `SkillRegistry` and `ToolInterceptor`.
- Implement basic `WorkflowState` models.

### Phase 2: Core Toolset (Week 2)
- Build `web_search`, `read_file`, and `run_python` (sandboxed).

### Phase 3: CLI Loop & Resume Integration (Week 3)
- Modify `CLISession` to handle the Interception & Resume loop.

### Phase 4: Workflow Graph (DAG) Engine (Week 4)
- Implement `WorkflowGraph` structure.
- Add `ConsensusEvaluator` for early exit logic.

### Phase 5: Recovery & Looping (Week 5)
- Build the `RecoveryRouter` and automated task re-assignment.

### Phase 6: Production Workflows & AI Influencer (Week 6)
- **VisualArtist:** Direct, automated integration with ComfyUI.
- **Bot Operations:** Automated market data fetching and risk monitoring.

---

## 5. Security & Invariants
- **Path Safety:** All file tools must use `realpath` + `startswith(project_path)`.
- **No SDKs:** Strictly use `subprocess.run(["claude", ...])`.
- **Transparency:** All tool calls, state transitions, and results are logged.

---

## 6. DeerFlow Skills Inventory & CLI Adaptation

**Research Date:** 2026-03-24

### 6.1 DeerFlow Built-in Tool Catalogue

| Tool | DeerFlow Library | Required Env Var | MAS Priority |
|------|-----------------|------------------|--------------|
| `web_search` | Tavily / DuckDuckGo / Brave | `TAVILY_API_KEY` (optional) | **P1** — Researcher agent |
| `web_fetch` | Jina AI reader API | `JINA_API_KEY` (optional) | **P1** — Researcher agent |
| `python_repl` | Docker sandbox / subprocess | None | **P1** — Tester/BackendDev |
| `bash` | OS shell (sandboxed) | None | **P2** — BackendDev |
| `read_file` | Python stdlib + fsspec | None | **P1** — All agents (done) |
| `write_file` | Python stdlib + fsspec | None | **P2** — BackendDev |
| `str_replace` | Python stdlib | None | **P2** — BackendDev |
| `ls` / `list_dir` | Python stdlib | None | **P1** — All agents (done) |
| `comfyui_submit` | httpx (local server) | None | **P1** — VisualArtist |
| `comfyui_poll` | httpx (local server) | None | **P1** — VisualArtist |

**Deferred (DeerFlow-only, not applicable to MAS):** `image_search`, `video_generation`, BytePlus InfoQuest (requires BytePlus contract), MCP server routing.

### 6.2 CLI Adaptation Design Per Tool

#### `web_search` → `mas/tools/web.py:web_search`
- **Library:** `httpx` + Tavily REST API (`api.tavily.com/search`); fallback to DuckDuckGo HTML scrape if no key
- **Env:** `TAVILY_API_KEY` — optional. Missing key → DuckDuckGo fallback (no error)
- **Output:** `list[{title, url, snippet}]` — max 5 results, truncated to 2000 tokens
- **Agent marker:** `[TOOL_CALL: web_search | {"query": "...", "max_results": 5}]`

#### `web_fetch` → `mas/tools/web.py:web_fetch`
- **Library:** `httpx` GET + `html2text` for Markdown conversion; Jina reader (`r.jina.ai/<url>`) if `JINA_API_KEY` set
- **Env:** `JINA_API_KEY` — optional. Missing → direct fetch + html2text
- **Output:** Markdown string, truncated at 3000 tokens with `[TRUNCATED]` notice
- **Agent marker:** `[TOOL_CALL: web_fetch | {"url": "https://..."}]`

#### `python_repl` → `mas/tools/sandbox.py:run_python`
- **Library:** `subprocess.run(["python3", "-c", code])` — no Docker in V1
- **Security:** Hard 30s timeout; no `shell=True`; strips `CLAUDECODE` from env
- **Output:** `{stdout, stderr, returncode}` — stdout truncated at 2000 chars
- **Agent marker:** `[TOOL_CALL: run_python | {"code": "import sys; print(sys.version)"}]`

#### `bash` → `mas/tools/sandbox.py:run_bash`
- **Library:** `subprocess.run(cmd, shell=False, ...)` — command passed as list, not string
- **Security:** Allowlist of safe commands: `["grep", "find", "ls", "cat", "wc", "head", "tail", "git"]`; all others raise `ToolSecurityError`
- **Timeout:** 30s hard limit
- **Agent marker:** `[TOOL_CALL: run_bash | {"cmd": ["grep", "-r", "pattern", "src/"]}]`

#### `write_file` → `mas/tools/filesystem.py:write_file`
- **Library:** Python stdlib `pathlib`
- **Security:** `realpath` + `startswith(project_path)` guard; max 100KB write
- **Behavior:** Creates parent dirs if missing; overwrites by default; `--dry-run` flag for preview
- **Agent marker:** `[TOOL_CALL: write_file | {"path": "src/foo.py", "content": "..."}]`

#### `str_replace` → `mas/tools/filesystem.py:str_replace`
- **Library:** Python stdlib — read, replace, write
- **Security:** Same path guard as `write_file`; requires exact `old_str` match (no regex)
- **Agent marker:** `[TOOL_CALL: str_replace | {"path": "src/foo.py", "old_str": "...", "new_str": "..."}]`

---

## 7. Phase 11: Advanced Skill Integration

> **Goal:** Bring MAS tool surface to parity with DeerFlow's built-in toolset. All tools use the Interception & Resume pattern. No new package dependencies except `html2text` (pure Python, zero native deps).

### Prerequisites
- Phase 9 complete (SkillRegistry + ToolInterceptor + CLISession loop)
- Phase 10 complete (WorkflowState three-layer model)

### Tasks

- [ ] **11.1 — `web_fetch` tool:** `mas/tools/web.py:web_fetch` — httpx GET + html2text Markdown conversion; Jina reader if `JINA_API_KEY` set; 3000-token truncation
- [ ] **11.2 — Tavily fallback chain:** `web_search` tries Tavily → DuckDuckGo HTML parse → `ToolExecutionError`; log which provider was used per call
- [ ] **11.3 — `run_bash` tool:** `mas/tools/sandbox.py:run_bash` — command allowlist enforcement; list-form args only (no `shell=True`); `ToolSecurityError` on blocked commands
- [ ] **11.4 — `write_file` tool:** `mas/tools/filesystem.py:write_file` — path guard + 100KB cap + parent dir creation
- [ ] **11.5 — `str_replace` tool:** `mas/tools/filesystem.py:str_replace` — exact-match only; raises `ToolExecutionError` if `old_str` not found (prevents silent no-ops)
- [ ] **11.6 — Registry expansion:** Add all 5 new tools to `skills/registry.yaml` with correct `agents` allowlists:
  - `web_fetch`: Researcher, Architect
  - `run_bash`: BackendDev, Tester (allowlist enforced at tool level too)
  - `write_file`: BackendDev only
  - `str_replace`: BackendDev only
- [ ] **11.7 — Tool result token budget:** `ToolInterceptor` enforces per-tool token caps before injecting results; truncation adds `[TRUNCATED — {n} chars omitted]` suffix
- [ ] **11.8 — `requires_env` soft degradation:** Tools with optional env vars (Tavily, Jina) log a `WARNING` at startup if key missing, but do not fail — use fallback path
- [ ] **11.9 — Integration tests:** `tests/test_advanced_tools.py` — live `web_fetch` (mocked httpx), `run_bash` allowlist acceptance + rejection, `write_file` path guard, `str_replace` no-match error
- [ ] **11.10 — `detail.md` update:** Add tool catalogue table with library, env var, agent allowlist, and token budget columns

**Milestone:** `Researcher` agent can call `web_search` + `web_fetch` in a single turn to gather and parse a source. `BackendDev` agent can call `run_bash` + `write_file` to locate and patch a file. All tool calls appear in `session-{id}.json`.
