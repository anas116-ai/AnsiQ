"""Crew — orchestrates a team of agents to accomplish complex tasks.

Supports:
- Pipeline (sequential): tasks execute in order, passing results forward
- Council (hierarchical): a coordinator agent delegates to specialist agents
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

import aiofiles
from pydantic import BaseModel, Field

from ansiq.core.agent import Agent
from ansiq.core.task import Task

logger = logging.getLogger(__name__)


class ProcessType(StrEnum):
    """The process strategy for task execution."""

    PIPELINE = "pipeline"
    """Tasks execute sequentially, passing context forward."""

    COUNCIL = "council"
    """A coordinator agent delegates tasks to specialist agents."""


class CrewResult(BaseModel):
    """Result of a crew execution."""

    tasks_output: list[str] = Field(default_factory=list)
    task_results: dict[str, Any] = Field(default_factory=dict)
    raw_output: str | None = None
    usage_metrics: dict[str, Any] = Field(default_factory=dict)


class Crew:
    """A team of agents working together on a set of tasks.

    Supports knowledge sources for RAG, trajectory recording,
    and self-improvement through batch training.

    Example:
        crew = Crew(
            agents=[researcher, analyst],
            tasks=[research_task, analysis_task],
            process=ProcessType.PIPELINE,
            knowledge=[FileSource("doc.md", Path("docs/manual.md"))],
        )
        result = await crew.kickoff(inputs={"topic": "AI Agents"})
    """

    def __init__(
        self,
        agents: list[Agent],
        tasks: list[Task],
        process: ProcessType = ProcessType.PIPELINE,
        manager_agent: Agent | None = None,
        verbose: bool = False,
        max_retries: int = 3,
        knowledge: list[Any] | None = None,
    ):
        self.agents = agents
        self.tasks = tasks
        self.process = process
        self.manager_agent = manager_agent
        self.verbose = verbose
        self.max_retries = max_retries
        self._knowledge_sources: list[Any] = knowledge or []
        self._rag_engine: Any | None = None

        # Assign agents to tasks if specified by name
        self._assign_agents_to_tasks()

        # Initialize RAG engine if knowledge sources provided
        if self._knowledge_sources:
            try:
                from ansiq.knowledge.engine import RAGEngine

                self._rag_engine = RAGEngine()
            except ImportError:
                pass

    async def add_knowledge(self, source: Any) -> bool:
        """Add a knowledge source to the crew.

        The source is automatically indexed for RAG retrieval.
        """
        self._knowledge_sources.append(source)
        if self._rag_engine:
            try:
                return await self._rag_engine.add_source(source)
            except Exception:
                return False
        return False

    async def index_knowledge(self) -> int:
        """Index all knowledge sources for RAG. Returns count of indexed chunks."""
        if not self._rag_engine or not self._knowledge_sources:
            return 0
        count = 0
        for source in self._knowledge_sources:
            try:
                if await self._rag_engine.add_source(source):
                    count += 1
            except Exception:
                pass
        return count

    def _attach_knowledge_to_agents(self) -> None:
        """Attach the RAG engine to agents that don't have their own knowledge."""
        if self._rag_engine:
            for agent in self.agents:
                if agent.knowledge is None:
                    agent.knowledge = self._rag_engine

    def _assign_agents_to_tasks(self) -> None:
        """Link tasks to agents based on task.agent references."""
        agent_map = {a.identity.role.lower(): a for a in self.agents}

        for task in self.tasks:
            if task.agent is None:
                continue
            if isinstance(task.agent, str):
                role_key = task.agent.lower()
                if role_key in agent_map:
                    task.agent = agent_map[role_key]
                else:
                    logger.warning(
                        "Agent '%s' not found for task. Available: %s",
                        task.agent,
                        list(agent_map.keys()),
                    )
                    task.agent = self.agents[0] if self.agents else None

    def add_agent(self, agent: Agent) -> None:
        """Add an agent to the crew."""
        self.agents.append(agent)

    def add_task(self, task: Task) -> None:
        """Add a task to the crew."""
        self.tasks.append(task)

    async def kickoff(
        self,
        inputs: dict[str, Any] | None = None,
    ) -> CrewResult:
        """Execute the crew's tasks with knowledge and trajectory support."""
        inputs = inputs or {}
        result = CrewResult()

        # Index knowledge sources if not already done
        if self._knowledge_sources and self._rag_engine:
            await self.index_knowledge()
            self._attach_knowledge_to_agents()

        if self.process == ProcessType.COUNCIL:
            await self._run_council(inputs, result)
        else:
            await self._run_pipeline(inputs, result)

        return result

    async def _run_pipeline(
        self,
        inputs: dict[str, Any],
        result: CrewResult,
    ) -> None:
        """Execute tasks sequentially in a pipeline."""
        logger.info("Starting pipeline execution with %d tasks", len(self.tasks))
        context: list[Task] = []

        for i, task in enumerate(self.tasks):
            if self.verbose:
                logger.info(
                    "Executing task %d/%d: %s", i + 1, len(self.tasks), task.description[:100]
                )

            agent = task.agent or self.agents[i % len(self.agents)]

            # Build task context from previous tasks
            task_context_parts = []
            if context:
                task_context_parts.append("Previous work:")
                for prev_task in context:
                    if hasattr(prev_task, "result") and prev_task.result:
                        task_context_parts.append(f"- {prev_task.description}:\n{prev_task.result}")

            # Template the task description with inputs
            try:
                task_description = task.description.format(**inputs)
            except KeyError:
                task_description = task.description

            # Add context from dependent tasks
            deps_context = task.get_context_text()
            if deps_context:
                task_context_parts.append(deps_context)

            full_context = "\n".join(task_context_parts) if task_context_parts else None

            # Execute the task
            response = await agent.run(
                task=task_description,
                context=full_context,
            )

            # Store result
            task.result = response.content if hasattr(response, "content") else str(response)
            result.task_results[task.description[:50]] = task.result
            result.tasks_output.append(task.result)

            # Write to output file if specified
            if task.output_file:
                try:
                    async with aiofiles.open(task.output_file, "w") as f:
                        await f.write(task.result)
                except Exception as e:
                    logger.warning("Could not write output file %s: %s", task.output_file, e)

            context.append(task)

        # Store raw output
        result.raw_output = "\n\n".join(result.tasks_output)

        if self.verbose:
            logger.info("Pipeline execution complete")

    async def _run_council(
        self,
        inputs: dict[str, Any],
        result: CrewResult,
    ) -> None:
        """Execute tasks using council (hierarchical) process.

        A manager/coordinator agent delegates to specialist agents.
        """
        logger.info("Starting council execution with %d agents", len(self.agents))

        coordinator = self.manager_agent or self.agents[0]
        specialists = [a for a in self.agents if a != coordinator]

        if not specialists:
            specialists = self.agents[1:] if len(self.agents) > 1 else self.agents
            if coordinator in specialists and len(specialists) > 1:
                specialists.remove(coordinator)

        # Coordinator delegates tasks to specialists
        plan_prompt = (
            "You are coordinating a team to accomplish the following goals:\n\n"
            "Tasks:\n"
            + "\n".join(f"- {t.description}" for t in self.tasks)
            + "\n\nAvailable specialists:\n"
            + "\n".join(f"- {a.identity.role}: {a.identity.goal}" for a in specialists)
            + "\n\nCreate a plan assigning each task to the best specialist."
        )

        if hasattr(inputs, "items"):
            plan_prompt += "\n\nInput parameters:\n"
            for key, value in inputs.items():
                plan_prompt += f"- {key}: {value}\n"

        plan_response = await coordinator.run(task=plan_prompt)
        result.task_results["plan"] = (
            plan_response.content if hasattr(plan_response, "content") else str(plan_response)
        )

        # Execute tasks with specialists
        for i, task in enumerate(self.tasks):
            specialist = specialists[i % len(specialists)] if specialists else coordinator

            try:
                task_description = task.description.format(**inputs)
            except KeyError:
                task_description = task.description

            task_context = (
                f"Overall context from coordinator:\n{result.task_results.get('plan', '')}"
            )
            response = await specialist.run(task=task_description, context=task_context)

            task.result = response.content if hasattr(response, "content") else str(response)
            result.task_results[task.description[:50]] = task.result
            result.tasks_output.append(task.result)

        result.raw_output = "\n\n".join(result.tasks_output)

        if self.verbose:
            logger.info("Council execution complete")

    async def kickoff_for_each(self, inputs_list: list[dict[str, Any]]) -> list[CrewResult]:
        """Execute the crew multiple times with different inputs."""
        results = []
        for inputs in inputs_list:
            result = await self.kickoff(inputs)
            results.append(result)
        return results

    def __repr__(self) -> str:
        return (
            f"Crew(agents={len(self.agents)}, tasks={len(self.tasks)}, "
            f"process='{self.process.value}')"
        )
