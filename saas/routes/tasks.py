"""Task Management API routes — CRUD and execution for tasks."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ansiq.core.task import Task as CoreTask
from ansiq.core.agent import Agent as CoreAgent

from saas.auth import get_current_user
from saas.database import get_db
from saas.models import TaskModel, User, UserRole

logger = logging.getLogger("ansiq.saas.routes.tasks")

router = APIRouter(prefix="/api/v1/tasks", tags=["Tasks"])


class TaskCreateRequest(BaseModel):
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    expected_output: str | None = None
    workspace_id: str | None = None


class TaskUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    expected_output: str | None = None
    is_active: bool | None = None


class TaskResponse(BaseModel):
    id: str
    name: str
    description: str
    expected_output: str | None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]
    total: int
    page: int
    page_size: int


class TaskRunRequest(BaseModel):
    context: dict | None = Field(default_factory=dict)


async def _get_task_or_404(task_id: str, user: User, db: AsyncSession):
    res = await db.execute(
        select(TaskModel).where(TaskModel.id == task_id, TaskModel.organization_id == user.organization_id)
    )
    task = res.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(req: TaskCreateRequest, user: Annotated[User, Depends(get_current_user)], db: AsyncSession = Depends(get_db)):
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can create tasks")

    task = TaskModel(
        name=req.name,
        description=req.description,
        expected_output=req.expected_output,
        workspace_id=req.workspace_id,
        organization_id=user.organization_id,
        created_by=user.id,
    )
    db.add(task)
    await db.flush()
    logger.info("Task created: %s (id=%s, org=%s, by=%s)", task.name, task.id, user.organization_id, user.id)
    return TaskResponse(id=task.id, name=task.name, description=task.description, expected_output=task.expected_output, is_active=task.is_active)


@router.get("", response_model=TaskListResponse)
async def list_tasks(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    q = select(TaskModel).where(TaskModel.organization_id == user.organization_id)
    count_res = await db.execute(select(func.count()).select_from(TaskModel).where(TaskModel.organization_id == user.organization_id))
    total = count_res.scalar() or 0
    offset = (page - 1) * page_size
    q = q.offset(offset).limit(page_size).order_by(TaskModel.id.desc())
    res = await db.execute(q)
    tasks = res.scalars().all()
    return TaskListResponse(tasks=[TaskResponse(id=t.id, name=t.name, description=t.description, expected_output=t.expected_output, is_active=t.is_active) for t in tasks], total=total, page=page, page_size=page_size)


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    task = await _get_task_or_404(task_id, user, db)
    return TaskResponse(id=task.id, name=task.name, description=task.description, expected_output=task.expected_output, is_active=task.is_active)


@router.put("/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, req: TaskUpdateRequest, user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can update tasks")
    task = await _get_task_or_404(task_id, user, db)
    if req.name is not None:
        task.name = req.name
    if req.description is not None:
        task.description = req.description
    if req.expected_output is not None:
        task.expected_output = req.expected_output
    if req.is_active is not None:
        task.is_active = req.is_active
    await db.flush()
    return TaskResponse(id=task.id, name=task.name, description=task.description, expected_output=task.expected_output, is_active=task.is_active)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: str, user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    if user.role not in (UserRole.ADMIN, UserRole.OWNER):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admins can delete tasks")
    task = await _get_task_or_404(task_id, user, db)
    await db.delete(task)
    await db.flush()


@router.post("/{task_id}/execute")
async def execute_task(task_id: str, req: TaskRunRequest, user: Annotated[User, Depends(get_current_user)] = None, db: AsyncSession = Depends(get_db)):
    task = await _get_task_or_404(task_id, user, db)
    if not task.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Task is not active")

    # Create a lightweight agent to run the task
    identity = {"role": "task-runner", "goal": task.name, "backstory": "autogenerated runner"}
    core_agent = CoreAgent(identity=identity)
    core_task = CoreTask(description=task.description, expected_output=task.expected_output or "")

    result = await core_agent.run(task=core_task.description, context=None, stream=False)
    content = result.content if hasattr(result, "content") else str(result)

    return {"status": "completed", "output": content}


__all__ = ["router"]
