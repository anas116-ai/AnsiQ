"""Base skill — a reusable capability that an agent can learn and execute."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class SkillResult(BaseModel):
    """Result of a skill execution."""

    success: bool = True
    output: str = ""
    data: Any = None
    error: str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class BaseSkill(ABC):
    """A reusable capability that an agent can learn, improve, and execute.

    Skills are more complex than tools — they represent learned procedures
    with steps, validation, and improvement over time.
    """

    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    category: str = "general"

    def __init__(self):
        if not self.name:
            self.name = self.__class__.__name__.lower()
        self._improvements: list[str] = []
        self._execution_count: int = 0

    def get_name(self) -> str:
        """Get the skill's name."""
        return self.name

    def get_description(self) -> str:
        """Get the skill's description."""
        return self.description

    def get_version(self) -> str:
        """Get the skill's version string."""
        return self.version

    @abstractmethod
    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute the skill with given parameters."""
        ...

    async def run(self, **kwargs: Any) -> str:
        """Convenience method to execute and return output."""
        result = await self.execute(**kwargs)
        return result.output

    def improve(self, feedback: str) -> None:
        """Record improvement feedback for this skill."""
        self._improvements.append(feedback)
        self._execution_count += 1
        logger.debug("Skill '%s' improved with feedback: %s", self.name, feedback[:100])

    def get_improvement_history(self) -> list[str]:
        """Get the list of improvement feedback."""
        return list(self._improvements)

    def get_execution_count(self) -> int:
        """Get the number of times this skill has been executed."""
        return self._execution_count

    def to_dict(self) -> dict[str, Any]:
        """Serialize skill to dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "category": self.category,
            "execution_count": self._execution_count,
            "improvements": self._improvements,
        }

    def __repr__(self) -> str:
        return f"Skill(name='{self.name}', version='{self.version}')"
