"""SkillRegistry — loads registry.yaml and resolves tools per agent (Phase 9.3)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from .models import FunctionalSkill, ToolParam

_REGISTRY_PATH = Path(__file__).parent.parent / "registry.yaml"


class SkillRegistry:
    """
    Loads FunctionalSkill definitions from registry.yaml.

    Usage:
        registry = SkillRegistry()
        tools = registry.tools_for_agent("BackendDev")
        schema = registry.schema_block("BackendDev")  # inject into system prompt
    """

    def __init__(self, registry_path: str | Path = _REGISTRY_PATH):
        self._path = Path(registry_path)
        self._tools: dict[str, FunctionalSkill] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        with open(self._path) as f:
            data = yaml.safe_load(f) or {}
        for entry in data.get("tools", []):
            params = [ToolParam(**p) for p in entry.pop("params", [])]
            skill = FunctionalSkill(**entry, params=params)
            self._tools[skill.name] = skill

    def get(self, name: str) -> FunctionalSkill | None:
        return self._tools.get(name)

    def tools_for_agent(self, agent_name: str) -> list[FunctionalSkill]:
        """Return all tools the agent is permitted to call."""
        return [t for t in self._tools.values() if t.agent_can_use(agent_name)]

    def schema_block(self, agent_name: str) -> str:
        """
        Generate a compact text block describing available tools.
        Injected into agent system prompts so agents know what they can call.
        """
        tools = self.tools_for_agent(agent_name)
        if not tools:
            return ""
        lines = ["## Available Tools", ""]
        lines.append("Emit `[TOOL_CALL: tool_name | {\"arg\": \"value\"}]` to call a tool.")
        lines.append("The orchestrator will execute it and resume with `[TOOL_RESULT: {...}]`.")
        lines.append("")
        for t in tools:
            schema = json.dumps(t.param_schema(), separators=(",", ":"))
            lines.append(f"### {t.name}")
            lines.append(f"{t.description}")
            lines.append(f"Params: `{schema}`")
            lines.append("")
        return "\n".join(lines)

    @property
    def all_tools(self) -> dict[str, FunctionalSkill]:
        return dict(self._tools)