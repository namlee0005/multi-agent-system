"""
ToolInterceptor — parses [TOOL_CALL] markers from CLI output (Phase 9.4).

Protocol:
  Agent emits:       [TOOL_CALL: tool_name | {"arg": "value"}]
  Orchestrator runs: execute_tool(tool_name, args, project_path)
  Orchestrator feeds back via --resume: [TOOL_RESULT: {...}]
"""

from __future__ import annotations

import json
import re
from typing import Any

from .models import ToolCall, ToolResult

# Matches: [TOOL_CALL: tool_name | {"key": "val"}]
_TOOL_CALL_RE = re.compile(
    r"\[TOOL_CALL:\s*(?P<name>[a-z_]+)\s*\|\s*(?P<args>\{.*?\})\s*\]",
    re.DOTALL,
)


def parse_tool_call(text: str) -> ToolCall | None:
    """
    Extract the first [TOOL_CALL: ...] marker from agent output.
    Returns None if no marker is found or the JSON args are malformed.
    """
    m = _TOOL_CALL_RE.search(text)
    if not m:
        return None
    try:
        args = json.loads(m.group("args"))
    except json.JSONDecodeError:
        return None
    return ToolCall(tool_name=m.group("name"), args=args)


def has_tool_call(text: str) -> bool:
    return bool(_TOOL_CALL_RE.search(text))


def strip_tool_call(text: str) -> str:
    """Remove the [TOOL_CALL: ...] marker from agent output."""
    return _TOOL_CALL_RE.sub("", text).strip()


def build_resume_prompt(original_prompt: str, agent_output: str, result: ToolResult) -> str:
    """
    Construct the prompt for the --resume call.
    Feeds back the tool result so the agent can continue its reasoning.
    """
    clean_output = strip_tool_call(agent_output)
    return (
        f"{original_prompt}\n\n"
        f"[Previous partial response]\n{clean_output}\n\n"
        f"{result.to_resume_marker()}\n\n"
        "Continue your response using the tool result above."
    )