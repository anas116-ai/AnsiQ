"""Export/Import routes — JSON bundles for portability.

Allows exporting and importing agents, crews, knowledge,
and full system state as JSON for backup, sharing, and migration.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

from ansiq.api.state import get_app_state

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Export ──


@router.get("/export/agents", response_model=list[dict[str, Any]])
async def export_agents():
    """Export all agents as a JSON-serializable list."""
    state = get_app_state()
    results = []
    for agent_id, agent in state.agents.items():
        results.append(
            {
                "id": agent_id,
                "identity": {
                    "role": agent.identity.role,
                    "goal": agent.identity.goal,
                    "backstory": agent.identity.backstory,
                },
                "config": {
                    "llm_provider": agent.config.llm_provider,
                    "llm_model": agent.config.llm_model,
                    "temperature": agent.config.temperature,
                    "max_tokens": agent.config.max_tokens,
                    "allow_delegation": agent.config.allow_delegation,
                    "verbose": agent.config.verbose,
                    "max_retries": agent.config.max_retries,
                    "thinking_mode": agent.config.thinking_mode,
                },
            }
        )
    return results


@router.get("/export/crews", response_model=list[dict[str, Any]])
async def export_crews():
    """Export all crews as a JSON-serializable list."""
    state = get_app_state()
    results = []
    for crew_id, crew in state.crews.items():
        agents = []
        for a in crew.agents:
            agents.append(
                {
                    "role": a.identity.role,
                    "goal": a.identity.goal,
                    "backstory": a.identity.backstory,
                    "llm_provider": a.config.llm_provider,
                    "llm_model": a.config.llm_model,
                }
            )
        tasks = []
        for t in crew.tasks:
            tasks.append(
                {
                    "description": t.description,
                    "expected_output": t.expected_output,
                    "agent_role": t.agent.identity.role if t.agent else None,
                }
            )
        results.append(
            {
                "id": crew_id,
                "agents": agents,
                "tasks": tasks,
                "process": crew.process.value
                if hasattr(crew.process, "value")
                else str(crew.process),
            }
        )
    return results


@router.get("/export/knowledge")
async def export_knowledge():
    """Export all knowledge sources and their content."""
    state = get_app_state()
    if not state.rag_engine:
        return {"sources": []}

    stats = state.rag_engine.get_stats()
    return {
        "sources": stats.get("sources", []),
        "stats": {
            "total_chunks": stats.get("store", {}).get("total_chunks", 0),
            "total_sources": len(stats.get("sources", [])),
        },
    }


@router.get("/export/all")
async def export_all():
    """Export the full system state as a single JSON bundle."""
    agents = await export_agents()
    crews = await export_crews()
    knowledge = await export_knowledge()
    return {
        "version": "1.0",
        "agents": agents,
        "crews": crews,
        "knowledge": knowledge,
    }


# ── Import ──


@router.post("/import/agents")
async def import_agents(payload: list[dict[str, Any]]):
    """Import agents from a JSON list (compatible with export format)."""
    state = get_app_state()
    from ansiq.core.agent import Agent, AgentConfig, AgentIdentity

    count = 0
    skipped = 0
    for item in payload:
        agent_id = item.get("id", "").strip()
        identity_data = item.get("identity", {})
        config_data = item.get("config", {})

        if not agent_id or not identity_data.get("role"):
            skipped += 1
            continue

        identity = AgentIdentity(
            role=identity_data["role"],
            goal=identity_data.get("goal", "Work"),
            backstory=identity_data.get("backstory", ""),
        )
        config = AgentConfig(
            identity=identity,
            llm_provider=config_data.get("llm_provider", "openai"),
            llm_model=config_data.get("llm_model", "gpt-4o"),
            temperature=config_data.get("temperature", 0.7),
            max_tokens=config_data.get("max_tokens", 4096),
            allow_delegation=config_data.get("allow_delegation", False),
            verbose=config_data.get("verbose", False),
            max_retries=config_data.get("max_retries", 3),
            thinking_mode=config_data.get("thinking_mode", "standard"),
        )

        agent = Agent(identity=identity, config=config)

        # Use the ID from export, or generate from role
        final_id = agent_id if agent_id else identity_data["role"].lower().replace(" ", "_")
        state.add_agent(final_id, agent)
        count += 1

    logger.info("Imported %d agents (skipped %d)", count, skipped)
    return {"imported": count, "skipped": skipped}


@router.post("/import/crews")
async def import_crews(payload: list[dict[str, Any]]):
    """Import crews from a JSON list (compatible with export format)."""
    state = get_app_state()
    from ansiq.core.agent import Agent, AgentConfig, AgentIdentity
    from ansiq.core.crew import Crew, ProcessType
    from ansiq.core.task import Task

    count = 0
    skipped = 0
    for item in payload:
        crew_id = item.get("id", "").strip()
        agents_data = item.get("agents", [])
        tasks_data = item.get("tasks", [])
        process_str = item.get("process", "pipeline")

        if not crew_id or not agents_data or not tasks_data:
            skipped += 1
            continue

        # Recreate agents
        crew_agents = []
        for aref in agents_data:
            identity = AgentIdentity(
                role=aref.get("role", "worker"),
                goal=aref.get("goal", "Work"),
                backstory=aref.get("backstory", ""),
            )
            config = AgentConfig(
                identity=identity,
                llm_provider=aref.get("llm_provider", "openai"),
                llm_model=aref.get("llm_model", "gpt-4o"),
            )
            agent = Agent(identity=identity, config=config)
            crew_agents.append(agent)

        agent_map = {a.identity.role.lower(): a for a in crew_agents}

        # Recreate tasks
        crew_tasks = []
        for tref in tasks_data:
            task = Task(
                description=tref.get("description", ""),
                expected_output=tref.get("expected_output", ""),
            )
            agent_role = tref.get("agent_role")
            if agent_role and agent_role.lower() in agent_map:
                task.agent = agent_map[agent_role.lower()]
            crew_tasks.append(task)

        process = ProcessType.PIPELINE
        if process_str.lower() == "council":
            process = ProcessType.COUNCIL

        crew = Crew(agents=crew_agents, tasks=crew_tasks, process=process)
        state.add_crew(crew_id, crew)
        count += 1

    logger.info("Imported %d crews (skipped %d)", count, skipped)
    return {"imported": count, "skipped": skipped}


@router.post("/import/all")
async def import_all(payload: dict[str, Any]):
    """Import a full system state bundle (compatible with /export/all)."""
    results = {"agents": None, "crews": None, "knowledge": None}
    version = payload.get("version", "unknown")

    if "agents" in payload and isinstance(payload["agents"], list):
        results["agents"] = await import_agents(payload["agents"])
    if "crews" in payload and isinstance(payload["crews"], list):
        results["crews"] = await import_crews(payload["crews"])

    logger.info("Full import complete (version %s): %s", version, results)
    return {"imported": results, "version": version}
