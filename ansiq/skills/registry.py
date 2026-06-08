"""Skill Registry — central registry for discovering and managing skills.

Supports registering, unregistering, listing, and searching skills.
"""

from __future__ import annotations

import logging
from typing import Any

from ansiq.skills.base import BaseSkill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """Global registry for skills that agents can discover and acquire."""

    _skills: dict[str, BaseSkill] = {}

    @classmethod
    def register(cls, skill: BaseSkill) -> None:
        """Register a skill globally."""
        cls._skills[skill.name] = skill
        logger.debug("Registered skill: %s v%s", skill.name, skill.version)

    @classmethod
    def register_class(cls, skill_cls: type[BaseSkill]) -> None:
        """Register a skill class (instantiates it first)."""
        instance = skill_cls()
        cls.register(instance)

    @classmethod
    def get(cls, name: str) -> BaseSkill | None:
        """Get a skill by name."""
        return cls._skills.get(name)

    @classmethod
    def unregister(cls, name: str) -> None:
        """Remove a skill from the registry."""
        cls._skills.pop(name, None)
        logger.debug("Unregistered skill: %s", name)

    @classmethod
    def list_skills(cls) -> list[BaseSkill]:
        """Get all registered skills."""
        return list(cls._skills.values())

    @classmethod
    def list_by_category(cls, category: str) -> list[BaseSkill]:
        """Get skills by category."""
        return [s for s in cls._skills.values() if s.category.lower() == category.lower()]

    @classmethod
    def search(cls, query: str) -> list[BaseSkill]:
        """Search skills by name or description."""
        query = query.lower()
        results = []
        for skill in cls._skills.values():
            if query in skill.name.lower() or query in skill.description.lower():
                results.append(skill)
        return results

    @classmethod
    def get_skill_map(cls) -> dict[str, dict[str, Any]]:
        """Get a summary map of all registered skills."""
        return {
            name: {
                "name": skill.name,
                "description": skill.description,
                "version": skill.version,
                "category": skill.category,
                "execution_count": skill.get_execution_count(),
            }
            for name, skill in cls._skills.items()
        }
