"""Crew management routes — create, list, run."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ansiq.api.models import (
    CrewCreateRequest,
    CrewListResponse,
    CrewResponse,
    CrewRunRequest,
    CrewRunResponse,
)
from ansiq.api.state import get_app_state

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=CrewResponse, status_code=201)
async def create_crew(req: CrewCreateRequest):
    """Create a new crew from agent/task definitions."""
    state = get_app_state()

    from ansiq.core.agent import Agent, AgentConfig, AgentIdentity
    from ansiq.core.crew import Crew, ProcessType
    from ansiq.core.task import Task

    # Create agents
    crew_agents = []
    for agent_ref in req.agents:
        identity = AgentIdentity(
            role=agent_ref.role,
            goal=agent_ref.goal or f"Act as {agent_ref.role}",
            backstory=agent_ref.backstory or f"An expert {agent_ref.role}",
        )
        config = AgentConfig(
            identity=identity,
            llm_provider=agent_ref.llm_provider,
            llm_model=agent_ref.llm_model,
        )
        agent = Agent(identity=identity, config=config)
        agent_id = agent_ref.role.lower().replace(" ", "_")
        state.add_agent(agent_id, agent)
        crew_agents.append(agent)

    # Create tasks
    crew_tasks = []
    for task_ref in req.tasks:
        assigned_agent = None
        if task_ref.agent_role:
            for c_agent in crew_agents:
                if c_agent.identity.role.lower() == task_ref.agent_role.lower():
                    assigned_agent = c_agent
                    break

        task = Task(
            description=task_ref.description,
            expected_output=task_ref.expected_output or "Completed",
            agent=assigned_agent,
        )
        crew_tasks.append(task)

    # Determine process type
    process = ProcessType.PIPELINE
    if req.process.lower() == "council":
        process = ProcessType.COUNCIL

    crew = Crew(
        agents=crew_agents,
        tasks=crew_tasks,
        process=process,
    )

    crew_id = req.name.lower().replace(" ", "_")
    state.add_crew(crew_id, crew)

    logger.info(
        "Created crew: %s (%d agents, %d tasks)", crew_id, len(crew_agents), len(crew_tasks)
    )

    return CrewResponse(
        id=crew_id,
        name=req.name,
        agents_count=len(crew_agents),
        tasks_count=len(crew_tasks),
        process=process.value,
    )


@router.get("", response_model=CrewListResponse)
async def list_crews():
    """List all crews in the shared state."""
    state = get_app_state()

    crews = []
    for cid, crew in state.crews.items():
        crews.append(
            CrewResponse(
                id=cid,
                name=cid,
                agents_count=len(crew.agents),
                tasks_count=len(crew.tasks),
                process=crew.process.value if hasattr(crew.process, "value") else str(crew.process),
            )
        )

    return CrewListResponse(crews=crews, total=len(crews))


@router.get("/{crew_id}", response_model=CrewResponse)
async def get_crew(crew_id: str):
    """Get a specific crew by ID."""
    state = get_app_state()
    crew = state.crews.get(crew_id)
    if not crew:
        raise HTTPException(status_code=404, detail=f"Crew '{crew_id}' not found")
    return CrewResponse(
        id=crew_id,
        name=crew_id,
        agents_count=len(crew.agents),
        tasks_count=len(crew.tasks),
        process=crew.process.value if hasattr(crew.process, "value") else str(crew.process),
    )


@router.delete("/{crew_id}", status_code=204)
async def delete_crew(crew_id: str):
    """Delete a crew by ID."""
    state = get_app_state()
    if not state.remove_crew(crew_id):
        raise HTTPException(status_code=404, detail=f"Crew '{crew_id}' not found")
    logger.info("Deleted crew: %s", crew_id)


@router.post("/{crew_id}/run", response_model=CrewRunResponse)
async def run_crew(crew_id: str, req: CrewRunRequest):
    """Execute a crew with optional inputs."""
    state = get_app_state()
    crew = state.crews.get(crew_id)
    if not crew:
        raise HTTPException(status_code=404, detail=f"Crew '{crew_id}' not found")

    try:
        result = await crew.kickoff(inputs=req.inputs)
        return CrewRunResponse(
            tasks_output=result.tasks_output,
            task_results=result.task_results,
            raw_output=result.raw_output or "",
        )
    except Exception as e:
        logger.error("Crew run failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
