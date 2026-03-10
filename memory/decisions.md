
### [2026-03-10] Rule: Human-in-the-Loop Approval for Planner Output

**Decision:** Implement a human-in-the-loop approval step after the Planner agent completes its initial task (analyzing requirements, proposing tech stack, architecture, and plan). Once the Planner's output (e.g., `spec.md` or a summary report) is reviewed and approved by the user, the rest of the agent pipeline will proceed autonomously without further manual intervention.

**Implementation details:**
- `orchestrator.py`: Modify to introduce a pause after the Planner agent finishes.
- `orchestrator.py`: Send a notification to the user (via `sessions_send`) with the Planner's output and prompt for approval (e.g., "Approve to continue?").
- `orchestrator.py`: Wait for a specific user response (e.g., "approve", "ok", "continue") to resume autonomous execution.
- `planner/SKILL.md`: Update to instruct the Planner to generate a clear, reviewable document/report as its final output.

**Action items:**
- [ ] Update `orchestrator.py` with approval gate logic.
- [ ] Update `planner/SKILL.md` to guide Planner's output for review.

---

