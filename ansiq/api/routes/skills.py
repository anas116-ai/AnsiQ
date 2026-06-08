"""Skill management routes — list, register."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ansiq.api.models import (
    SkillCreateRequest,
    SkillListResponse,
    SkillResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("", response_model=SkillListResponse)
async def list_skills():
    """List all registered skills."""
    from ansiq.skills.registry import SkillRegistry

    skills = SkillRegistry.list_skills()
    items = [
        SkillResponse(
            name=s.name,
            description=s.description,
            category=s.category,
            version=s.version,
        )
        for s in skills
    ]
    return SkillListResponse(skills=items, total=len(items))


@router.post("", response_model=SkillResponse, status_code=201)
async def create_skill(req: SkillCreateRequest):
    """Register a new skill (basic registration, no LLM generation)."""
    from ansiq.skills.registry import SkillRegistry

    try:
        from ansiq.skills.learner import DynamicSkill

        skill = DynamicSkill(
            name=req.name,
            description=req.description,
            category=req.category,
            implementation="result = f'Executed {req.name}'",
        )
        SkillRegistry.register(skill)
        return SkillResponse(
            name=skill.name,
            description=skill.description,
            category=skill.category,
            version=skill.version,
        )
    except Exception as e:
        logger.error("Failed to create skill: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
