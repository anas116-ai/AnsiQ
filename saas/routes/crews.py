"""Crew Management API routes — CRUD and execution for crews."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ansiq.core.crew import Crew as CoreCrew, ProcessType
from ansiq.core.agent import Agent as CoreAgent
from ansiq.core.task import Task as CoreTask

from saas.auth import get_current_user
from saas.database import get_db
from saas.models import CrewModel, User, UserRole

logger = logging.getLogger("ansiq.saas.routes.crews")

router = APIRouter(prefix="/api/v1/crews", tags=["Crews"])


class CrewCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    agents: list[dict] = Field(..., min_length=1)
    tasks: list[dict] = Field(..., min_length=1)
    process: str = Field("pipeline")


class CrewUpdateRequest(BaseModel):
    name: str | None = None
    agents: list[dict] | None = None
    tasks: list[dict] | None = None
    process: str | None = None
    is_active: bool | None = None


class CrewResponse(BaseModel):
    id: str
    name: str
    agents_count: int
    tasks_count: int
    process: str
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class CrewListResponse(BaseModel):
    crews: list[CrewResponse]
    total: int
    page: int
    page_size: int


class CrewRunRequest(BaseModel):
    inputs: dict = Field(default_factory=dict)


async def _get_crew_or_404(crew_id: str, user: User, db: AsyncSession):
    res = await db.execute(
        select(CrewModel).where(CrewModel.id == crew_id, CrewModel.organization_id == user.organization_id)
    )
    crew = res.scalar_one_or_none()
    if not crew:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Crew not found")
    return crew


@router.post("", response_model=CrewResponse, status_code=status.HTTP_201_CREATED)
async def create_crew(req: CrewCreateRequest, user: Annotated[User, Depends(get_current_user)], db: AsyncSession = Depends(get_db)):
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can create crews")

    crew = CrewModel(
        name=req.name,
        agents=req.agents,
        tasks=req.tasks,
        process=req.process,
        organization_id=user.organization_id,
        created_by=user.id,
    )
    db.add(crew)
    await db.flush()
    logger.info("Crew created: %s (id=%s, org=%s, by=%s)", crew.name, crew.id, user.organization_id, user.id)
    return CrewResponse(
        id=crew.id,
        name=crew.name,
        agents_count=len(crew.agents or []),
        tasks_count=len(crew.tasks or []),
        process=crew.process,
        is_active=crew.is_active,
    )


@router.get("", response_model=CrewListResponse)
async def list_crews(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    q = select(CrewModel).where(CrewModel.organization_id == user.organization_id)
    count_res = await db.execute(select(func.count()).select_from(CrewModel).where(CrewModel.organization_id == user.organization_id))
    total = count_res.scalar() or 0
    offset = (page - 1) * page_size
    q = q.offset(offset).limit(page_size).order_by(CrewModel.id.desc())
    res = await db.execute(q)
    crews = res.scalars().all()
    return CrewListResponse(
        crews=[CrewResponse(id=c.id, name=c.name, agents_count=len(c.agents or []), tasks_count=len(c.tasks or []), process=c.process, is_active=c.is_active) for c in crews],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{crew_id}", response_model=CrewResponse)
async def get_crew(crew_id: str, user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    crew = await _get_crew_or_404(crew_id, user, db)
    return CrewResponse(id=crew.id, name=crew.name, agents_count=len(crew.agents or []), tasks_count=len(crew.tasks or []), process=crew.process, is_active=crew.is_active)


@router.put("/{crew_id}", response_model=CrewResponse)
async def update_crew(crew_id: str, req: CrewUpdateRequest, user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can update crews")
    crew = await _get_crew_or_404(crew_id, user, db)
    if req.name is not None:
        crew.name = req.name
    if req.agents is not None:
        crew.agents = req.agents
    if req.tasks is not None:
        crew.tasks = req.tasks
    if req.process is not None:
        crew.process = req.process
    if req.is_active is not None:
        crew.is_active = req.is_active
    await db.flush()
    return CrewResponse(id=crew.id, name=crew.name, agents_count=len(crew.agents or []), tasks_count=len(crew.tasks or []), process=crew.process, is_active=crew.is_active)


@router.delete("/{crew_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_crew(crew_id: str, user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can delete crews")
    crew = await _get_crew_or_404(crew_id, user, db)
    await db.delete(crew)
    await db.flush()


@router.post("/{crew_id}/execute")
async def execute_crew(crew_id: str, req: CrewRunRequest, user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    crew = await _get_crew_or_404(crew_id, user, db)
    if not crew.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Crew is not active")

    # Build core Agent and Task objects from stored JSON
    core_agents = []
    for a in crew.agents or []:
        identity = {"role": a.get("role"), "goal": a.get("goal", ""), "backstory": a.get("backstory", "")}
        config = {"llm_provider": a.get("llm_provider", "openai"), "llm_model": a.get("llm_model", "gpt-4o"), "temperature": a.get("temperature", 0.7)}
        core_agents.append(CoreAgent(identity=identity, config=config))

    core_tasks = []
    for t in crew.tasks or []:
        task = CoreTask(description=t.get("description"), expected_output=t.get("expected_output", ""))
        core_tasks.append(task)

    process = ProcessType(crew.process) if crew.process in ProcessType.__members__.values() else ProcessType.PIPELINE

    core_crew = CoreCrew(agents=core_agents, tasks=core_tasks, process=ProcessType(crew.process))
    result = await core_crew.kickoff(inputs=req.inputs)

    return {
        "tasks_output": result.tasks_output,
        "task_results": result.task_results,
        "raw_output": result.raw_output,
        "usage_metrics": result.usage_metrics,
    }


__all__ = ["router"]
