# Multi-Agent System (MAS) Architecture

## Overview
The MAS is a parallel, debate-driven orchestration framework designed to produce high-fidelity technical specifications and implementations. It leverages specialized agents that challenge and refine each other's outputs.

## Core Components
- **Orchestrator:** Manages the lifecycle of a debate session.
- **ContextStore:** Thread-safe, RLock-protected key/value store for shared state.
- **Specialist Agents:** LLM-backed entities with unique system prompts and roles.
- **Validator/Reviewer:** Quality-control gates for agent responses and file artifacts.

## State Management (Optimized)
The system uses a **Hybrid Session-Context** model:

1.  **Static Base Context:** System prompts and core project descriptions are marked for **Prompt Caching** to reduce latency and cost.
2.  **Role-Based Pruning:** Project files (like `spec.md`) are selectively injected based on the agent's role (e.g., Security agents receive auth-related snippets; FrontendDev receives UI-related snippets).
3.  **Debate Deltas:** Round 2 agents receive a summarized "Round 1 Synthesis" rather than raw, repetitive proposal dumps.

## Data Flow
1.  **Selection:** Planner identifies required agents.
2.  **Round 1 (Proposals):** Agents generate initial designs in parallel.
3.  **Round 2 (Challenges):** Agents critique and refine based on pruned context and summarized history.
4.  **Synthesis:** Planner resolves conflicts and produces the final recommendation.
5.  **Artifact Gate:** All `<write_file>` tags are reviewed by the `CodeReviewer` agent before disk commit.

## Security
- **Path Sanitization:** All file writes are restricted to the workspace root using absolute path resolution and prefix validation.
- **Credential Protection:** Secrets are never injected into prompts; environment variables are used for backend configuration.