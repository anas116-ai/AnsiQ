"""Task — a unit of work assigned to an agent."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field


class Task(BaseModel):
    """A unit of work for an agent to execute.

    Tasks have a description, expected output, and can be chained together.
    """

    description: str = Field(description="What needs to be done")
    expected_output: str = Field(description="What the output should look like")
    agent: Any | None = None
    tools: list[Any] = Field(default_factory=list)
    context: list[Task] | None = None
    output_file: str | None = None
    output_json: type | None = None
    output_pydantic: type | None = None
    human_input: bool = False
    allow_delegation: bool = False
    async_execution: bool = False
    callback: Callable | None = None
    result: str | None = None

    model_config = {"arbitrary_types_allowed": True}

    def __init__(self, **data):
        super().__init__(**data)
        if self.context is None:
            self.context = []
        self.result = data.get("result")

    def get_context_text(self) -> str:
        """Get the consolidated context from dependent tasks."""
        if not self.context:
            return ""
        parts = []
        for task in self.context:
            if task.result:
                parts.append(f"Previous task result:\n{task.result}")
        return "\n\n".join(parts)

    def __repr__(self) -> str:
        agent_name = self.agent.identity.role if hasattr(self.agent, "identity") else "unassigned"
        return f"Task(description='{self.description[:50]}...', agent='{agent_name}')"
