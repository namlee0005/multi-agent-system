"""Pydantic models for the Functional Skill system (Phase 9.1)."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


class ToolParam(BaseModel):
    """Schema descriptor for a single tool parameter."""
    name: str
    type: Literal["string", "integer", "float", "boolean", "list", "dict"]
    description: str
    required: bool = True
    default: Any = None

    @model_validator(mode="after")
    def default_only_when_optional(self) -> "ToolParam":
        if self.required and self.default is not None:
            raise ValueError(f"Param '{self.name}': required params must not have a default")
        return self


class FunctionalSkill(BaseModel):
    """Registry entry for a single executable tool."""
    name: str = Field(description="Unique snake_case tool identifier")
    description: str = Field(description="One-sentence description for the agent")
    params: list[ToolParam] = Field(default_factory=list)
    allowed_agents: list[str] = Field(
        default_factory=list,
        description="Agent names that may call this tool. Empty = all agents.",
    )
    timeout_s: int = Field(default=30, ge=1, le=300)

    def agent_can_use(self, agent_name: str) -> bool:
        """Return True if the agent is permitted to call this tool."""
        return not self.allowed_agents or agent_name in self.allowed_agents

    def param_schema(self) -> dict[str, Any]:
        """Return a compact JSON Schema fragment for prompt injection."""
        props = {}
        required = []
        for p in self.params:
            props[p.name] = {"type": p.type, "description": p.description}
            if p.default is not None:
                props[p.name]["default"] = p.default
            if p.required:
                required.append(p.name)
        return {
            "type": "object",
            "properties": props,
            "required": required,
        }


class ToolCall(BaseModel):
    """Parsed emission from an agent: [TOOL_CALL: name | {args}]"""
    tool_name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result to be fed back to the agent via --resume."""
    tool_name: str
    success: bool
    data: Any = None
    error: str | None = None

    def to_resume_marker(self) -> str:
        """Format as the text marker injected into the resumed prompt."""
        import json
        payload = self.model_dump(mode="json")
        return f"[TOOL_RESULT: {json.dumps(payload)}]"