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
