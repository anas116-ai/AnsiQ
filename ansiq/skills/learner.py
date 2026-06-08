"""Skill Learner — enables agents to autonomously create and improve skills.

Uses an LLM to generate new skills from natural language descriptions
and improve existing skills based on feedback and usage patterns.
"""

from __future__ import annotations

import logging
from typing import Any

from ansiq.skills.base import BaseSkill, SkillResult
from ansiq.skills.registry import SkillRegistry

logger = logging.getLogger(__name__)


class DynamicSkill(BaseSkill):
    """A skill created dynamically at runtime.

    Uses an LLM-generated implementation.
    """

    def __init__(
        self,
        name: str,
        description: str,
        implementation: str,
        category: str = "general",
    ):
        self._dynamic_name = name
        self._dynamic_description = description
        self._implementation = implementation
        self.category = category
        super().__init__()

    @property
    def name(self) -> str:
        return self._dynamic_name

    @name.setter
    def name(self, value: str) -> None:
        self._dynamic_name = value

    @property
    def description(self) -> str:
        return self._dynamic_description

    @description.setter
    def description(self, value: str) -> None:
        self._dynamic_description = value

    async def execute(self, **kwargs: Any) -> SkillResult:
        """Execute the dynamic skill."""
        try:
            exec_globals: dict[str, Any] = {"kwargs": kwargs}
            exec(self._implementation, exec_globals)
            if "execute" in exec_globals:
                return await exec_globals["execute"](**kwargs)
            # Check for a 'result' variable set by the implementation
            result = exec_globals.get("result", "Executed dynamic skill")
            return SkillResult(success=True, output=str(result))
        except Exception as e:
            logger.error("Dynamic skill execution failed: %s", e)
            return SkillResult(success=False, error=str(e))


class SkillLearner:
    """Enables agents to autonomously create and improve skills.

    Uses LLM-based generation to create new skills from descriptions,
    and to improve existing skills based on execution feedback.
    """

    def __init__(self, llm_provider=None):
        self._llm = llm_provider

    async def create_skill(
        self,
        name: str,
        description: str,
        category: str = "general",
        llm: Any | None = None,
    ) -> BaseSkill:
        """Create a new skill from a natural language description.

        Uses an LLM to generate the skill implementation.
        """
        provider = llm or self._llm
        if provider is None:
            # Fallback: create a simple dynamic skill
            return DynamicSkill(
                name=name,
                description=description,
                implementation="result = f'Executed {name} with {kwargs}'",
                category=category,
            )

        prompt = (
            f"Create a Python async function called 'execute' that implements this skill.\\n\\n"
            f"Skill Name: {name}\\n"
            f"Description: {description}\\n"
            f"Category: {category}\\n\\n"
            f"The function signature should be: async def execute(**kwargs) -> dict:\\n"
            f"Return a dict with 'success' (bool) and 'output' (str) keys.\\n\\n"
            f"Write ONLY the function body, no imports or class definitions."
        )

        from ansiq.llm.base import LLMMessage

        response = await provider.chat(
            [
                LLMMessage.system("You are a code generator that creates skill implementations."),
                LLMMessage.user(prompt),
            ]
        )

        implementation = response.content.strip()
        # Clean up markdown code blocks if present
        if implementation.startswith("```"):
            implementation = implementation.split("\\n", 1)[1]
            if "```" in implementation:
                implementation = implementation.rsplit("```", 1)[0]

        skill = DynamicSkill(
            name=name,
            description=description,
            implementation=implementation,
            category=category,
        )

        SkillRegistry.register(skill)
        logger.info("Created new skill: %s (category: %s)", name, category)
        return skill

    async def improve_skill(
        self,
        skill: BaseSkill,
        feedback: str,
        llm: Any | None = None,
    ) -> BaseSkill:
        """Improve an existing skill based on feedback.

        Records the feedback and, if an LLM is available,
        refines the skill's implementation.
        """
        skill.improve(feedback)

        if isinstance(skill, DynamicSkill) and (llm or self._llm):
            provider = llm or self._llm
            prompt = (
                f"Improve this skill implementation based on feedback.\\n\\n"
                f"Skill: {skill.name}\\n"
                f"Description: {skill.description}\\n"
                f"Current Implementation:\\n{skill._implementation}\\n\\n"
                f"Feedback: {feedback}\\n\\n"
                f"Write ONLY the improved function body, no imports or class definitions."
            )

            from ansiq.llm.base import LLMMessage

            response = await provider.chat(
                [
                    LLMMessage.system(
                        "You are improving a skill implementation based on user feedback."
                    ),
                    LLMMessage.user(prompt),
                ]
            )

            new_impl = response.content.strip()
            if new_impl.startswith("```"):
                new_impl = new_impl.split("\\n", 1)[1]
                if "```" in new_impl:
                    new_impl = new_impl.rsplit("```", 1)[0]

            skill._implementation = new_impl
            logger.info("Improved skill: %s", skill.name)

        return skill

    async def learn_from_demonstration(
        self,
        demonstration: str,
        skill_name: str,
        llm: Any | None = None,
    ) -> BaseSkill:
        """Create a skill by observing a demonstration.

        The demonstration is a natural language description of
        how to perform a task, which the LLM converts into a skill.
        """
        provider = llm or self._llm
        if provider is None:
            return await self.create_skill(skill_name, demonstration)

        prompt = (
            f"Learn from this demonstration and create a reusable skill.\\n\\n"
            f"Skill Name: {skill_name}\\n"
            f"Demonstration:\\n{demonstration}\\n\\n"
            f"First, summarize what this skill does in 1-2 sentences.\\n"
            f"Then, write a Python async function 'execute(**kwargs)' that implements the skill.\\n"
            f"Return a dict with 'success' (bool) and 'output' (str) keys."
        )

        from ansiq.llm.base import LLMMessage

        response = await provider.chat(
            [
                LLMMessage.system(
                    "You learn skills from demonstrations and implement them as reusable code."
                ),
                LLMMessage.user(prompt),
            ]
        )

        content = response.content.strip()

        # Try to extract description and implementation
        parts = content.split("def execute", 1)
        description = parts[0].strip() if len(parts) > 1 else skill_name
        implementation = ("def execute" + parts[1]) if len(parts) > 1 else content

        if implementation.startswith("```"):
            implementation = implementation.split("\\n", 1)[1]
            if "```" in implementation:
                implementation = implementation.rsplit("```", 1)[0]

        skill = DynamicSkill(
            name=skill_name,
            description=description[:200],
            implementation=implementation,
            category="learned",
        )

        SkillRegistry.register(skill)
        logger.info("Learned skill from demonstration: %s", skill_name)
        return skill
