"""
RecoveryRouter: automated error handling and task re-assignment (Phase 10.4).

Routes failed tasks based on error type:
  - transient errors (timeout, rate limit) → retry same agent
  - validation errors → retry with corrective feedback
  - hard errors (binary missing, path traversal) → escalate / skip
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from .state import WorkflowState, TaskState


RecoveryAction = Literal["retry_same", "retry_with_feedback", "reassign", "skip", "escalate"]

_TRANSIENT_PATTERNS = [
    r"timeout",
    r"rate.?limit",
    r"503",
    r"429",
    r"connection",
]

_VALIDATION_PATTERNS = [
    r"validation.?fail",
    r"too short",
    r"mismatched.*tag",
    r"expected.*json",
]

_HARD_PATTERNS = [
    r"binary.?not.?found",
    r"path traversal",
    r"permission",
    r"BinaryNotFoundError",
]


@dataclass
class RecoveryDecision:
    action: RecoveryAction
    feedback: str | None = None
    reassign_to: str | None = None
    reason: str = ""


class RecoveryRouter:
    """
    Inspect a failed TaskState and decide how to recover.

    Usage:
        router = RecoveryRouter()
        decision = router.route(failed_task, state)
        if decision.action == "retry_same":
            state.update_task(task.task_id, status="pending", error=None)
        elif decision.action == "skip":
            state.update_task(task.task_id, status="failed")  # keep failed, move on
    """

    def __init__(self, fallback_agent: str = "Architect") -> None:
        self.fallback_agent = fallback_agent

    def route(self, task: TaskState, state: WorkflowState) -> RecoveryDecision:
        error = (task.error or "").lower()

        # Hard failures — do not retry
        for pat in _HARD_PATTERNS:
            if re.search(pat, error, re.IGNORECASE):
                return RecoveryDecision(
                    action="escalate",
                    reason=f"Hard error — requires operator intervention: {task.error}",
                )

        # Exhausted retries
        if task.attempt >= task.max_attempts:
            return RecoveryDecision(
                action="skip",
                reason=f"Max attempts ({task.max_attempts}) reached. Skipping task.",
            )

        # Transient errors — plain retry
        for pat in _TRANSIENT_PATTERNS:
            if re.search(pat, error, re.IGNORECASE):
                return RecoveryDecision(
                    action="retry_same",
                    reason=f"Transient error detected ({pat}). Retrying.",
                )

        # Validation errors — retry with corrective feedback
        for pat in _VALIDATION_PATTERNS:
            if re.search(pat, error, re.IGNORECASE):
                feedback = (
                    f"Your previous response failed validation: {task.error}. "
                    "Please correct the issues and resubmit."
                )
                return RecoveryDecision(
                    action="retry_with_feedback",
                    feedback=feedback,
                    reason="Validation failure — retrying with feedback.",
                )

        # Reassign to fallback agent for unknown errors
        if task.assigned_agent and task.assigned_agent != self.fallback_agent:
            return RecoveryDecision(
                action="reassign",
                reassign_to=self.fallback_agent,
                reason=f"Unknown error from {task.assigned_agent}. Reassigning to {self.fallback_agent}.",
            )

        return RecoveryDecision(
            action="retry_same",
            reason="Unknown error, attempting retry.",
        )

    def apply(self, decision: RecoveryDecision, task_id: str, state: WorkflowState) -> None:
        """Apply a recovery decision to the workflow state in-place."""
        task = state.tasks[task_id]

        if decision.action == "skip":
            state.update_task(task_id, status="failed")

        elif decision.action == "escalate":
            state.update_task(task_id, status="failed", error=f"ESCALATED: {decision.reason}")

        elif decision.action == "retry_same":
            state.update_task(task_id, status="pending", error=None)

        elif decision.action == "retry_with_feedback":
            new_desc = f"{task.description}\n\n{decision.feedback}"
            state.update_task(task_id, status="pending", description=new_desc, error=None)

        elif decision.action == "reassign":
            state.update_task(
                task_id,
                status="pending",
                assigned_agent=decision.reassign_to,
                error=None,
            )