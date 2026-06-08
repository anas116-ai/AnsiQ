"""Tool system — agents use tools to interact with the world.

Each tool has a name, description, and execution logic.
Tools can be built-in, custom, or MCP-based.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ToolParameter(BaseModel):
    """Parameter definition for a tool."""

    name: str = Field(description="Parameter name")
    type: str = Field(description="Parameter type (string, integer, boolean, etc.)")
    description: str = Field(default="", description="Parameter description")
    required: bool = Field(default=True, description="Whether the parameter is required")


class ToolResult(BaseModel):
    """Result of a tool execution."""

    success: bool = Field(default=True)
    output: str = Field(default="")
    data: Any = Field(default=None)
    error: str | None = None


class BaseTool(ABC):
    """Base class for all tools.

    Subclass this to create custom tools for agents.
    """

    name: str = ""
    description: str = ""
    parameters: list[ToolParameter] = []

    def __init__(self):
        if not self.name:
            self.name = self.__class__.__name__.lower()

    def get_name(self) -> str:
        """Get the tool's name."""
        return self.name

    def get_description(self) -> str:
        """Get the tool's description for LLM consumption."""
        desc = self.description
        if self.parameters:
            desc += "\n\nParameters:"
            for param in self.parameters:
                required = "required" if param.required else "optional"
                desc += f"\n- {param.name} ({param.type}, {required}): {param.description}"
        return desc

    def to_function_schema(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible function schema."""
        properties = {}
        required_params = []

        for param in self.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if param.required:
                required_params.append(param.name)

        schema: dict[str, Any] = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                },
            },
        }
        if required_params:
            schema["function"]["parameters"]["required"] = required_params

        return schema

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with given parameters."""
        ...

    async def run(self, **kwargs: Any) -> str:
        """Convenience method to execute and return output string."""
        result = await self.execute(**kwargs)
        return result.output

    def __repr__(self) -> str:
        return f"Tool(name='{self.name}')"
