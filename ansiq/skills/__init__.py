"""Skill system — autonomous skill creation, improvement, and registry.

Skills are composable capabilities that agents can learn and refine.
"""

from ansiq.skills.base import BaseSkill, SkillResult
from ansiq.skills.learner import SkillLearner
from ansiq.skills.registry import SkillRegistry

__all__ = [
    "BaseSkill",
    "SkillResult",
    "SkillRegistry",
    "SkillLearner",
]
