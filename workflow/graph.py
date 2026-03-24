"""
WorkflowGraph: DAG-based non-linear execution engine (Phase 10.2).

Nodes are TaskState entries. Edges are implicit via TaskState.dependencies.
Execution is topological: a node runs only when all its dependencies are complete.
"""

from __future__ import annotations

from collections import deque
from typing import Callable, Any

from .state import WorkflowState, TaskState


NodeHandler = Callable[[TaskState, WorkflowState], tuple[str, str | None]]
"""Signature: (task, state) -> (new_status, output_or_error)"""


class WorkflowGraph:
    """
    Registers task handlers and drives execution until the graph is complete
    or a non-recoverable failure occurs.

    Usage:
        graph = WorkflowGraph()
        graph.register("research", research_handler)
        graph.register("implement", implement_handler)
        final_state = graph.run(initial_state)
    """

    def __init__(self) -> None:
        self._handlers: dict[str, NodeHandler] = {}

    def register(self, task_type: str, handler: NodeHandler) -> None:
        """Register a callable for a task type (matched against task_id prefix)."""
        self._handlers[task_type] = handler

    def _resolve_handler(self, task: TaskState) -> NodeHandler | None:
        """Find handler by longest matching prefix of task_id."""
        for key in sorted(self._handlers, key=len, reverse=True):
            if task.task_id.startswith(key):
                return self._handlers[key]
        return self._handlers.get("default")

    def run(
        self,
        state: WorkflowState,
        on_task_start: Callable[[TaskState], None] | None = None,
        on_task_end: Callable[[TaskState], None] | None = None,
    ) -> WorkflowState:
        """
        Drive the DAG to completion.

        Each iteration:
          1. Find all ready tasks (dependencies satisfied, status=pending)
          2. Execute them (sequentially; parallel via ThreadPoolExecutor in future)
          3. Update state
          4. Repeat until complete or stuck (no progress made)
        """
        max_iterations = len(state.tasks) * 2 + 1  # safety bound
        iteration = 0

        while not state.is_complete() and iteration < max_iterations:
            ready = state.ready_tasks()
            if not ready:
                # No progress possible — remaining tasks are blocked or failed deps
                break

            for task in ready:
                state.update_task(task.task_id, status="running", attempt=task.attempt + 1)
                if on_task_start:
                    on_task_start(state.tasks[task.task_id])

                handler = self._resolve_handler(task)
                if handler is None:
                    state.update_task(task.task_id, status="failed", error="No handler registered")
                    continue

                try:
                    new_status, result = handler(task, state)
                    if new_status == "complete":
                        state.update_task(task.task_id, status="complete", output=result)
                    else:
                        state.update_task(task.task_id, status="failed", error=result)
                except Exception as e:
                    state.update_task(task.task_id, status="failed", error=str(e))

                if on_task_end:
                    on_task_end(state.tasks[task.task_id])

            iteration += 1

        return state