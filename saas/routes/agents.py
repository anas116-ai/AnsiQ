"""Agent Management API routes — CRUD operations for agents.

Provides REST endpoints for creating, reading, updating, and deleting agents
within a SaaS organization, with proper tenant scoping and access control.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import get_current_user, require_role
from saas.database import get_db
from saas.models import User, UserRole

logger = logging.getLogger("ansiq.saas.routes.agents")

router = APIRouter(prefix="/api/v1/agents", tags=["Agents"])


# ── Schemas ────────────────────────────────────────────────────────────


class AgentCreateRequest(BaseModel):
    """Request to create a new agent."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    model: str = Field(..., min_length=1, max_length=100)
    instructions: str | None = Field(None, max_length=10000)
    temperature: float = Field(0.7, ge=0, le=2.0)
    max_tokens: int = Field(4096, ge=1, le=32768)
    tools: list[str] | None = Field(default=None, description="List of tool names")


class AgentUpdateRequest(BaseModel):
    """Request to update an agent."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    instructions: str | None = Field(None, max_length=10000)
    temperature: float | None = Field(None, ge=0, le=2.0)
    max_tokens: int | None = Field(None, ge=1, le=32768)
    is_active: bool | None = Field(None)


class AgentResponse(BaseModel):
    """Response containing agent details."""

    id: str
    name: str
    description: str | None
    model: str
    temperature: float
    max_tokens: int
    is_active: bool
    created_at: str
    updated_at: str

    model_config = ConfigDict(from_attributes=True)


class AgentListResponse(BaseModel):
    """Response containing paginated list of agents."""

    total: int
    page: int
    page_size: int
    agents: list[AgentResponse]


class AgentExecuteRequest(BaseModel):
    """Request to execute an agent."""

    input_text: str = Field(..., min_length=1, max_length=10000)
    max_iterations: int = Field(5, ge=1, le=100)
    timeout_seconds: int = Field(300, ge=10, le=3600)


# ── Helper Functions ───────────────────────────────────────────────────


async def _get_agent_or_404(
    agent_id: str,
    user: User,
    db: AsyncSession,
):
    """Get agent by ID with tenant scoping and authorization."""
    # Import Agent here to avoid circular imports
    from saas.models import Agent as AgentModel

    result = await db.execute(
        select(AgentModel).where(
            AgentModel.id == agent_id,
            AgentModel.organization_id == user.organization_id,  # Tenant scoping
        )
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return agent


# ── Routes ─────────────────────────────────────────────────────────────


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    req: AgentCreateRequest,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent in the current organization."""
    from saas.models import Agent as AgentModel

    # Only admins and owners can create agents
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can create agents",
        )

    agent = AgentModel(
        name=req.name,
        description=req.description,
        model=req.model,
        instructions=req.instructions,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
        organization_id=user.organization_id,
        created_by=user.id,
    )
    db.add(agent)
    await db.flush()

    logger.info(
        "Agent created: %s (id=%s, org=%s, by=%s)",
        agent.name,
        agent.id,
        user.organization_id,
        user.id,
    )

    return AgentResponse.from_orm(agent)


@router.get("", response_model=AgentListResponse)
async def list_agents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_active: bool | None = Query(None),
    user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """List agents for the current organization (paginated)."""
    from saas.models import Agent as AgentModel

    # Build query with tenant scoping
    query = select(AgentModel).where(
        AgentModel.organization_id == user.organization_id
    )

    # Optional active filter
    if is_active is not None:
        query = query.where(AgentModel.is_active == is_active)

    # Get total count
    count_result = await db.execute(
        select(func.count()).select_from(AgentModel).where(
            AgentModel.organization_id == user.organization_id
        )
    )
    total = count_result.scalar() or 0

    # Get paginated results
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size).order_by(AgentModel.created_at.desc())
    result = await db.execute(query)
    agents = result.scalars().all()

    logger.info(
        "Agents listed: page=%d, page_size=%d, total=%d, org=%s",
        page,
        page_size,
        total,
        user.organization_id,
    )

    return AgentListResponse(
        total=total,
        page=page,
        page_size=page_size,
        agents=[AgentResponse.from_orm(a) for a in agents],
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: str,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific agent by ID (with tenant scoping)."""
    agent = await _get_agent_or_404(agent_id, user, db)
    return AgentResponse.from_orm(agent)


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str,
    req: AgentUpdateRequest,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Update an agent (admin only)."""
    # Check authorization
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can update agents",
        )

    agent = await _get_agent_or_404(agent_id, user, db)

    # Update fields if provided
    if req.name is not None:
        agent.name = req.name
    if req.description is not None:
        agent.description = req.description
    if req.instructions is not None:
        agent.instructions = req.instructions
    if req.temperature is not None:
        agent.temperature = req.temperature
    if req.max_tokens is not None:
        agent.max_tokens = req.max_tokens
    if req.is_active is not None:
        agent.is_active = req.is_active

    await db.flush()

    logger.info(
        "Agent updated: %s (id=%s, by=%s)",
        agent.name,
        agent.id,
        user.id,
    )

    return AgentResponse.from_orm(agent)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: str,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Delete an agent (admin only)."""
    # Check authorization
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete agents",
        )

    agent = await _get_agent_or_404(agent_id, user, db)

    await db.delete(agent)
    await db.flush()

    logger.info(
        "Agent deleted: %s (id=%s, by=%s)",
        agent.name,
        agent.id,
        user.id,
    )


@router.post("/{agent_id}/execute")
async def execute_agent(
    agent_id: str,
    req: AgentExecuteRequest,
    user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_db),
):
    """Execute an agent and return streaming results.

    This is a placeholder that returns immediate results.
    For production, this should use Server-Sent Events (SSE) for streaming.
    """
    agent = await _get_agent_or_404(agent_id, user, db)

    if not agent.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Agent is not active",
        )

    logger.info(
        "Agent execution started: %s (input_length=%d, by=%s)",
        agent.name,
        len(req.input_text),
        user.id,
    )

    # Placeholder: Return a mock execution result
    # TODO: Integrate with actual agent execution engine
    return {
        "status": "completed",
        "output": f"Agent '{agent.name}' processed input successfully",
        "iterations": 1,
        "tokens_used": 100,
        "execution_time_ms": 125,
    }


__all__ = ["router"]
