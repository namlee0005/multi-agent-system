"""
WorkflowState: three-layer state model (Phase 10.1).

Layers:
  conversation — message history between agents and orchestrator
  task         — current job definition, status, and outputs
  world        — external facts: project files, timestamps, environment
"""

from __future__ import annotations

import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


class Message(BaseModel):
    role: Literal["agent", "orchestrator", "tool", "human"]
    agent: str | None = None
    content: str
    timestamp: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


class TaskState(BaseModel):
    task_id: str
    description: str
    assigned_agent: str | None = None
    status: Literal["pending", "running", "complete", "failed", "retrying"] = "pending"
    attempt: int = 0
    max_attempts: int = 3
    output: str | None = None
    error: str | None = None
    dependencies: list[str] = Field(default_factory=list)  # task_ids this depends on

    @model_validator(mode="after")
    def attempt_within_bounds(self) -> "TaskState":
        if self.attempt > self.max_attempts:
            raise ValueError(f"attempt {self.attempt} exceeds max_attempts {self.max_attempts}")
        return self


class WorldState(BaseModel):
    project_path: str | None = None
    project_description: str = ""
    known_files: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    session_id: str | None = None
    started_at: datetime.datetime = Field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )


class WorkflowState(BaseModel):
    """Unified three-layer state container passed through the DAG."""

    # Layer 1: conversation history
    conversation: list[Message] = Field(default_factory=list)

    # Layer 2: task map keyed by task_id
    tasks: dict[str, TaskState] = Field(default_factory=dict)

    # Layer 3: world / environment
    world: WorldState = Field(default_factory=WorldState)

    def add_message(self, role: str, content: str, agent: str | None = None) -> None:
        self.conversation.append(Message(role=role, content=content, agent=agent))

    def add_task(self, task: TaskState) -> None:
        self.tasks[task.task_id] = task

    def update_task(self, task_id: str, **kwargs: Any) -> None:
        if task_id not in self.tasks:
            raise KeyError(f"Task '{task_id}' not found in workflow state")
        task = self.tasks[task_id]
        updated = task.model_copy(update=kwargs)
        self.tasks[task_id] = updated

    def ready_tasks(self) -> list[TaskState]:
        """Return tasks whose dependencies are all complete."""
        complete = {tid for tid, t in self.tasks.items() if t.status == "complete"}
        return [
            t for t in self.tasks.values()
            if t.status == "pending" and set(t.dependencies).issubset(complete)
        ]

    def is_complete(self) -> bool:
        return all(t.status in ("complete", "failed") for t in self.tasks.values())

    def has_failures(self) -> bool:
        return any(t.status == "failed" for t in self.tasks.values())