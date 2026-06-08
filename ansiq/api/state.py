"""Shared application state — separated to avoid circular imports.

Routes import get_app_state() from here instead of from server.py.
Server imports AppState from here as well.

Agents and crews are persisted to SQLite via ApiPersistence so they
survive server restarts.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ansiq.api.persistence import ApiPersistence

logger = logging.getLogger(__name__)


class AppState:
    """Shared state for the API server — holds agents, crews, and stores.

    This is a singleton accessed via get_app_state() dependency.
    Agents and crews are persisted to SQLite.
    """

    def __init__(self, db_path: str | None = None):
        self.persistence = ApiPersistence(db_path=db_path)
        self.agents: dict[str, Any] = {}
        self.crews: dict[str, Any] = {}
        self.memory_store: Any = None
        self.rag_engine: Any = None
        self.start_time: float = time.time()

        # Load persisted agents and crews
        self._load_all()

    def _load_all(self) -> None:
        """Reconstruct agents and crews from SQLite storage."""
        from ansiq.core.agent import Agent, AgentConfig, AgentIdentity
        from ansiq.core.crew import Crew, ProcessType
        from ansiq.core.task import Task

        for row in self.persistence.load_agents():
            try:
                identity = AgentIdentity(
                    role=row["role"],
                    goal=row["goal"],
                    backstory=row.get("backstory", ""),
                )
                config = AgentConfig(
                    identity=identity,
                    llm_provider=row.get("llm_provider", "openai"),
                    llm_model=row.get("llm_model", "gpt-4o"),
                    temperature=row.get("temperature", 0.7),
                )
                agent = Agent(identity=identity, config=config)
                self.agents[row["id"]] = agent
            except Exception as e:
                logger.warning("Failed to load agent '%s': %s", row.get("id"), e)

        for row in self.persistence.load_crews():
            try:
                # Build agent-role mapping from stored JSON
                task_agent_roles: dict[int, str] = {}
                for i, tref in enumerate(row.get("tasks", [])):
                    agent_role = tref.get("agent_role")
                    if agent_role:
                        task_agent_roles[i] = agent_role

                crew_agents = []
                for aref in row.get("agents", []):
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

                crew_tasks = []
                for i, tref in enumerate(row.get("tasks", [])):
                    task = Task(
                        description=tref.get("description", ""),
                        expected_output=tref.get("expected_output", ""),
                    )
                    # Assign agent by role
                    agent_role = task_agent_roles.get(i)
                    if agent_role:
                        role_key = agent_role.lower()
                        if role_key in agent_map:
                            task.agent = agent_map[role_key]
                    crew_tasks.append(task)

                process = ProcessType.PIPELINE
                if row.get("process", "pipeline").lower() == "council":
                    process = ProcessType.COUNCIL

                crew = Crew(
                    agents=crew_agents,
                    tasks=crew_tasks,
                    process=process,
                )
                self.crews[row["id"]] = crew

            except Exception as e:
                logger.warning("Failed to load crew '%s': %s", row.get("id"), e)

        if self.agents:
            logger.info("Loaded %d agents from disk", len(self.agents))
        if self.crews:
            logger.info("Loaded %d crews from disk", len(self.crews))

    def add_agent(self, agent_id: str, agent: Any) -> None:
        """Add an agent and persist to disk."""
        self.agents[agent_id] = agent
        self.persistence.save_agent(
            agent_id=agent_id,
            role=agent.identity.role,
            goal=agent.identity.goal,
            backstory=agent.identity.backstory,
            llm_provider=agent.config.llm_provider,
            llm_model=agent.config.llm_model,
            temperature=agent.config.temperature,
        )

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent and delete from disk."""
        if agent_id in self.agents:
            del self.agents[agent_id]
            self.persistence.delete_agent(agent_id)
            return True
        return False

    def add_crew(self, crew_id: str, crew: Any) -> None:
        """Add a crew and persist to disk."""
        self.crews[crew_id] = crew
        # Extract serializable agent refs
        agent_refs = []
        for a in crew.agents:
            agent_refs.append(
                {
                    "role": a.identity.role,
                    "goal": a.identity.goal,
                    "backstory": a.identity.backstory,
                    "llm_provider": a.config.llm_provider,
                    "llm_model": a.config.llm_model,
                }
            )
        # Extract serializable task refs
        task_refs = []
        for t in crew.tasks:
            task_refs.append(
                {
                    "description": t.description,
                    "expected_output": t.expected_output,
                    "agent_role": t.agent.identity.role if t.agent else None,
                }
            )
        self.persistence.save_crew(
            crew_id=crew_id,
            name=crew_id,
            process=crew.process.value if hasattr(crew.process, "value") else str(crew.process),
            agents=agent_refs,
            tasks=task_refs,
        )

    def remove_crew(self, crew_id: str) -> bool:
        """Remove a crew and delete from disk."""
        if crew_id in self.crews:
            del self.crews[crew_id]
            self.persistence.delete_crew(crew_id)
            return True
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "agents_count": len(self.agents),
            "crews_count": len(self.crews),
            "memory_available": self.memory_store is not None,
            "rag_available": self.rag_engine is not None,
            "uptime_seconds": round(time.time() - self.start_time, 2),
        }


_app_state: AppState | None = None


def get_app_state() -> AppState:
    """Get the shared application state.

    Used by route handlers as a FastAPI dependency.
    """
    global _app_state
    if _app_state is None:
        _app_state = AppState()
    return _app_state


def reset_app_state(db_path: str | None = None) -> None:
    """Reset the application state (useful for testing).

    Args:
        db_path: Optional custom database path for persistence isolation.
    """
    global _app_state
    _app_state = AppState(db_path=db_path)
