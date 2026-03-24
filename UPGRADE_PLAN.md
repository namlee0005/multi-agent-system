# MAS Functional Skills Upgrade Plan (100% CLI Edition)

**Date:** 2026-03-24  
**Strategy:** Pure CLI Implementation (No SDK)

---

## 1. Concept: Functional vs. Instructional Skills

The MAS system is evolving from **Instructional Skills** (static guidelines in `SKILL.md`) to include **Functional Skills** (executable tools like web search, file management, and ComfyUI interaction).

To comply with the requirement of **NOT using SDKs**, we will implement "Tool Use" via a pattern called **Interception & Resume**.

---

## 2. The Interception & Resume Pattern

Since we are using the `claude` and `gemini` CLI tools, we will not use native API function calling. Instead, we use a text-based protocol:

1.  **Emission:** The Agent, guided by its system prompt, emits a specific text marker when it needs a tool:  
    `[TOOL_CALL: tool_name | {"arg": "value"}]`
2.  **Interception:** The `Orchestrator` (specifically the `CLISession` loop) scans the CLI output for this marker.
3.  **Execution:** If a marker is found, the `Orchestrator` stops further processing, parses the JSON arguments, and executes the corresponding Python function locally.
4.  **Resume:** The `Orchestrator` then re-invokes the CLI using the `--resume` flag (introduced in Phase 6), feeding the result back:  
    `claude --resume [session_id] "[TOOL_RESULT: {"data": "..."}]"`
5.  **Completion:** The Agent receives the result as a new turn in the conversation, processes it, and provides the final answer.

---

## 3. Tool Registry Schema

Tools will be defined in a structured format in `skills/registry.yaml`:

```yaml
tools:
  - name: web_search
    description: "Search the web for info."
    callable_path: "mas.tools.web:search"
    params:
      query: "string"
  - name: run_python
    description: "Execute python code safely."
    callable_path: "mas.tools.sandbox:execute"
    params:
      code: "string"
```

---

## 4. Implementation Roadmap

### Phase 1: The Foundation (Week 1)
- Create `SkillRegistry` to load and manage tool definitions.
- Implement `ToolInterceptor` to parse `[TOOL_CALL]` markers.

### Phase 2: Core Toolset (Week 2)
- Build `web_search` tool (via Tavily/Serper).
- Build `read_file` / `list_dir` with strict path security.
- Build `run_python` using `subprocess` with timeouts.

### Phase 3: CLI Loop Integration (Week 3)
- Modify `CLISession` to handle the Interception & Resume loop.
- Support up to 3 recursive tool calls per turn.
- Ensure 100% compatibility with existing `claude` and `gemini` CLI commands.

### Phase 4: Production Workflows (Week 4)
- **VisualArtist:** Direct integration with ComfyUI.
- **BackendDev:** Automated code execution and testing.

---

## 5. Security & Invariants
- **Path Safety:** All file tools must use `realpath` + `startswith(project_path)`.
- **No SDKs:** Strictly use `subprocess.run(["claude", ...])`.
- **Transparency:** All tool calls and results are logged in `session-*.json`.
- **Timeouts:** All tool executions must have a hard timeout (default 30s).
