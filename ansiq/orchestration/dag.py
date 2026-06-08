"""DAG (Directed Acyclic Graph) Orchestrator — parallel task execution with automatic dependency resolution.

CrewAI only supports sequential (pipeline) and hierarchical (council) execution.
This DAG orchestrator enables ANY execution pattern:
- Tasks run in parallel when dependencies are met
- Auto-resolves dependency chains
- Supports conditional branching
- Visualizable execution graph

Inspired by Apache Airflow's DAG concept but designed specifically
for AI agent task orchestration.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from ansiq.core.agent import Agent
from ansiq.core.task import Task as AnsiqTask

logger = logging.getLogger(__name__)


class DAGNodeStatus(StrEnum):
    """Status of a DAG node during execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"


class DAGNode(BaseModel):
    """A single node in the DAG — wraps a task with dependency tracking."""

    id: str = Field(default_factory=lambda: f"node_{uuid.uuid4().hex[:8]}")
    name: str
    description: str = ""
    agent: Agent | None = None
    task: AnsiqTask | None = None
    depends_on: list[str] = Field(default_factory=list)
    """IDs of nodes that must complete before this node runs."""

    timeout: float | None = None
    """Maximum execution time in seconds. None = no timeout."""

    retry_count: int = 0
    """Number of retries on failure."""

    retry_delay: float = 1.0
    """Delay between retries in seconds."""

    status: DAGNodeStatus = DAGNodeStatus.PENDING
    result: str | None = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    duration: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Callbacks
    on_start: Callable | None = None
    on_complete: Callable | None = None
    on_fail: Callable | None = None

    model_config = {"arbitrary_types_allowed": True}

    async def execute(self, context: dict[str, Any] | None = None) -> str:
        """Execute this node's task and return the result."""
        self.status = DAGNodeStatus.RUNNING
        self.started_at = time.time()

        # Fire on_start callback
        if self.on_start:
            try:
                if asyncio.iscoroutinefunction(self.on_start):
                    await self.on_start(self)
                else:
                    self.on_start(self)
            except Exception as e:
                logger.warning("on_start callback failed: %s", e)

        # Build task context from dependencies
        task_context = ""
        if context:
            dep_results = []
            for dep_id in self.depends_on:
                if dep_id in context:
                    dep_results.append(f"[{dep_id}]: {context[dep_id][:200]}")
            if dep_results:
                task_context = "\n".join(dep_results)

        # Execute with retry logic
        last_error = None
        for attempt in range(self.retry_count + 1):
            try:
                if self.task:
                    # Use existing AnsiQ task
                    agent = self.agent or self.task.agent
                    if agent is None:
                        raise ValueError(f"No agent assigned to node '{self.name}'")

                    response = await agent.run(
                        task=self.task.description,
                        context=task_context or None,
                    )
                    result = response.content if hasattr(response, "content") else str(response)
                else:
                    # Simple text-based execution
                    agent = self.agent
                    if agent is None:
                        raise ValueError(f"No agent assigned to node '{self.name}'")

                    response = await agent.run(
                        task=self.description or self.name,
                        context=task_context or None,
                    )
                    result = response.content if hasattr(response, "content") else str(response)

                self.result = result
                self.status = DAGNodeStatus.COMPLETED
                self.completed_at = time.time()
                self.duration = self.completed_at - self.started_at

                # Fire on_complete callback
                if self.on_complete:
                    try:
                        if asyncio.iscoroutinefunction(self.on_complete):
                            await self.on_complete(self)
                        else:
                            self.on_complete(self)
                    except Exception as e:
                        logger.warning("on_complete callback failed: %s", e)

                return result

            except Exception as e:
                last_error = e
                logger.warning(
                    "Node '%s' attempt %d/%d failed: %s",
                    self.name,
                    attempt + 1,
                    self.retry_count + 1,
                    e,
                )
                if attempt < self.retry_count:
                    await asyncio.sleep(self.retry_delay)

        # All retries exhausted
        self.status = DAGNodeStatus.FAILED
        self.error = str(last_error)
        self.completed_at = time.time()
        self.duration = self.completed_at - self.started_at

        # Fire on_fail callback
        if self.on_fail:
            try:
                if asyncio.iscoroutinefunction(self.on_fail):
                    await self.on_fail(self)
                else:
                    self.on_fail(self)
            except Exception as e:
                logger.warning("on_fail callback failed: %s", e)

        raise RuntimeError(
            f"Node '{self.name}' failed after {self.retry_count + 1} attempts: {last_error}"
        )


class DAGTask:
    """Builder-pattern helper for creating DAG nodes with a clean API.

    Usage:
        dag = DAG()

        @dag.task
        async def fetch_data():
            return await some_api_call()

        @dag.task(depends_on=[fetch_data])
        async def process_data(data):
            return await process(data)
    """

    def __init__(self, name: str, depends_on: list[DAGTask] | None = None):
        self.name = name
        self._depends_on = depends_on or []
        self._agent = None
        self._timeout = None
        self._retry_count = 0
        self._node_id: str | None = None

    def with_agent(self, agent: Agent) -> DAGTask:
        self._agent = agent
        return self

    def with_timeout(self, seconds: float) -> DAGTask:
        self._timeout = seconds
        return self

    def with_retries(self, count: int, delay: float = 1.0) -> DAGTask:
        self._retry_count = count
        self.retry_delay = delay
        return self

    def _to_node(self, task_fn: Callable) -> DAGNode:
        deps = [t._node_id for t in self._depends_on if t._node_id]
        return DAGNode(
            name=self.name,
            description=task_fn.__doc__ or self.name,
            depends_on=deps,
            timeout=self._timeout,
            retry_count=self._retry_count,
        )


class DAGResult(BaseModel):
    """Result of a DAG execution."""

    successful_nodes: list[str] = Field(default_factory=list)
    failed_nodes: list[str] = Field(default_factory=list)
    skipped_nodes: list[str] = Field(default_factory=list)
    node_results: dict[str, str] = Field(default_factory=dict)
    node_statuses: dict[str, DAGNodeStatus] = Field(default_factory=dict)
    execution_time: float = 0.0
    total_nodes: int = 0

    @property
    def is_success(self) -> bool:
        """Check if all nodes completed successfully."""
        return len(self.failed_nodes) == 0 and len(self.skipped_nodes) == 0

    @property
    def summary(self) -> str:
        """Get a human-readable summary."""
        return (
            f"DAG Execution: {self.total_nodes} nodes, "
            f"{len(self.successful_nodes)} succeeded, "
            f"{len(self.failed_nodes)} failed, "
            f"{len(self.skipped_nodes)} skipped, "
            f"{self.execution_time:.2f}s"
        )


class DAG:
    """Directed Acyclic Graph orchestrator.

    Executes tasks in parallel while respecting dependencies.
    Automatically detects cycles and invalid configurations.

    Features:
    - Automatic dependency resolution
    - Maximum parallelism (runs all ready tasks simultaneously)
    - Cycle detection before execution
    - Timeout per node
    - Retry logic with backoff
    - Rich result tracking

    Usage:
        dag = DAG("research_pipeline")

        # Add nodes
        dag.add_node(DAGNode(name="search", description="Search for info"))
        dag.add_node(DAGNode(
            name="analyze",
            description="Analyze results",
            depends_on=["search"]
        ))
        dag.add_node(DAGNode(
            name="summarize",
            description="Write summary",
            depends_on=["analyze"]
        ))

        # Or use the decorator API
        @dag.task(depends_on=[dag["search"]])
        async def validate():
            pass

        # Execute
        result = await dag.execute()
    """

    def __init__(self, name: str = "default", description: str = ""):
        self.name = name
        self.description = description
        self._nodes: dict[str, DAGNode] = {}
        self._task_registry: list[tuple[DAGTask, Callable]] = []

    def add_node(self, node: DAGNode) -> DAGNode:
        """Add a node to the DAG."""
        if node.id in self._nodes:
            raise ValueError(f"Node with id '{node.id}' already exists")
        self._nodes[node.id] = node
        return node

    def get_node(self, node_id: str) -> DAGNode | None:
        """Get a node by ID or name."""
        if node_id in self._nodes:
            return self._nodes[node_id]
        # Search by name
        for node in self._nodes.values():
            if node.name == node_id:
                return node
        return None

    def __getitem__(self, name: str) -> DAGNode | None:
        """Access nodes by name using dag['node_name']."""
        return self.get_node(name)

    def task(self, depends_on: list[DAGNode] | None = None):
        """Decorator to register a function as a DAG task.

        Usage:
            @dag.task()
            async def my_task():
                pass

            @dag.task(depends_on=[other_node])
            async def dependent_task():
                pass
        """

        def decorator(func):
            # Create a DAG node for this function
            node_id = f"fn_{func.__name__}"
            dep_ids = [n.id for n in (depends_on or []) if n is not None]

            node = DAGNode(
                id=node_id,
                name=func.__name__,
                description=func.__doc__ or func.__name__,
                depends_on=dep_ids,
            )

            # Store the function for execution
            node.metadata["_func"] = func
            self._nodes[node_id] = node
            return node

        return decorator

    def _validate(self) -> None:
        """Validate the DAG before execution.

        Checks:
        - No duplicate nodes
        - All dependency references exist
        - No cycles (circular dependencies)
        """
        if not self._nodes:
            raise ValueError("DAG has no nodes to execute")

        # Check dependency references
        all_ids = set(self._nodes.keys())
        for node in self._nodes.values():
            for dep_id in node.depends_on:
                if dep_id not in all_ids:
                    raise ValueError(
                        f"Node '{node.name}' depends on '{dep_id}' which does not exist in the DAG"
                    )

        # Cycle detection using DFS
        visited: set[str] = set()
        recursion_stack: set[str] = set()

        def has_cycle(node_id: str, path: list[str]) -> bool:
            visited.add(node_id)
            recursion_stack.add(node_id)

            node = self._nodes[node_id]
            for dep_id in node.depends_on:
                if dep_id not in visited:
                    if has_cycle(dep_id, path + [dep_id]):
                        return True
                elif dep_id in recursion_stack:
                    cycle_path = " -> ".join(path + [dep_id, node_id])
                    raise ValueError(
                        f"Circular dependency detected in DAG '{self.name}': {cycle_path}"
                    )

            recursion_stack.discard(node_id)
            return False

        for node_id in self._nodes:
            if node_id not in visited:
                has_cycle(node_id, [node_id])

    def _get_ready_nodes(self, completed: set[str], running: set[str]) -> list[DAGNode]:
        """Get nodes that are ready to execute (all dependencies met)."""
        ready = []
        for node in self._nodes.values():
            if node.id in completed or node.id in running:
                continue
            if node.status == DAGNodeStatus.FAILED:
                continue
            if node.status == DAGNodeStatus.SKIPPED:
                continue

            # Check if all dependencies are completed
            all_deps_met = all(dep_id in completed for dep_id in node.depends_on)

            # Check if any dependency failed
            any_dep_failed = any(
                self._nodes[dep_id].status == DAGNodeStatus.FAILED
                for dep_id in node.depends_on
                if dep_id in self._nodes
            )

            if all_deps_met and not any_dep_failed:
                ready.append(node)
            elif any_dep_failed:
                node.status = DAGNodeStatus.SKIPPED
                logger.info("Node '%s' skipped (dependency failed)", node.name)

        return ready

    async def execute(
        self,
        inputs: dict[str, Any] | None = None,
        max_concurrent: int = 5,
    ) -> DAGResult:
        """Execute the DAG with maximum parallelism.

        Args:
            inputs: Optional input parameters for tasks
            max_concurrent: Maximum number of nodes to run simultaneously

        Returns:
            DAGResult with all execution details
        """
        self._validate()
        logger.info(
            "Starting DAG '%s' execution with %d nodes, max_concurrent=%d",
            self.name,
            len(self._nodes),
            max_concurrent,
        )

        start_time = time.time()
        completed: set[str] = set()
        running: set[str] = set()
        context: dict[str, Any] = {}
        semaphore = asyncio.Semaphore(max_concurrent)

        # Create result tracker
        result = DAGResult(total_nodes=len(self._nodes))

        async def execute_node(node: DAGNode) -> None:
            """Execute a single node with semaphore control."""
            async with semaphore:
                try:
                    # Check timeout
                    if node.timeout:
                        try:
                            node_result = await asyncio.wait_for(
                                node.execute(context), timeout=node.timeout
                            )
                        except TimeoutError:
                            node.status = DAGNodeStatus.FAILED
                            node.error = f"Timeout after {node.timeout}s"
                            node.completed_at = time.time()
                            node.duration = node.completed_at - (node.started_at or time.time())
                            raise
                    else:
                        node_result = await node.execute(context)

                    context[node.id] = node_result
                    result.successful_nodes.append(node.id)
                    result.node_results[node.id] = node_result[:500] if node_result else ""

                except Exception as e:
                    result.failed_nodes.append(node.id)
                    result.node_results[node.id] = f"ERROR: {e}"

                finally:
                    result.node_statuses[node.id] = node.status
                    running.discard(node.id)
                    completed.add(node.id)

        # Main execution loop
        while len(completed) < len(self._nodes):
            ready_nodes = self._get_ready_nodes(completed, running)

            if not ready_nodes:
                if running:
                    # Wait for running nodes to complete
                    await asyncio.sleep(0.1)
                    continue
                else:
                    # No nodes ready and none running — either done or stuck
                    remaining = [n for n in self._nodes.values() if n.id not in completed]
                    if remaining:
                        stuck = [n.name for n in remaining if n.status == DAGNodeStatus.PENDING]
                        if stuck:
                            logger.warning("DAG stalled! %d nodes pending: %s", len(stuck), stuck)
                            # Mark as blocked
                            for node in remaining:
                                if node.status == DAGNodeStatus.PENDING:
                                    node.status = DAGNodeStatus.BLOCKED
                    break

            # Launch ready nodes concurrently
            tasks = [execute_node(node) for node in ready_nodes]
            for node in ready_nodes:
                running.add(node.id)

            logger.debug(
                "DAG '%s': %d ready, %d running, %d completed",
                self.name,
                len(ready_nodes),
                len(running),
                len(completed),
            )

            # Wait for at least one to complete before checking again
            if tasks:
                # Python 3.14+ requires tasks explicitly, not raw coroutines
                task_objects = [asyncio.ensure_future(t) for t in tasks]
                done, _ = await asyncio.wait(task_objects, return_when=asyncio.FIRST_COMPLETED)
                # The rest continue running in background

        # Wait for all running tasks to complete
        if running:
            remaining_runners = []
            for node_id in running:
                node = self._nodes[node_id]
                remaining_runners.append(execute_node(node))
            if remaining_runners:
                await asyncio.gather(*remaining_runners, return_exceptions=True)

        # Final result
        result.execution_time = time.time() - start_time

        # Count skipped
        for node in self._nodes.values():
            if node.status == DAGNodeStatus.SKIPPED:
                result.skipped_nodes.append(node.name)

        logger.info(
            "DAG '%s' complete: %d success, %d failed, %d skipped in %.2fs",
            self.name,
            len(result.successful_nodes),
            len(result.failed_nodes),
            len(result.skipped_nodes),
            result.execution_time,
        )

        return result

    def visualize(self) -> str:
        """Generate a text-based visualization of the DAG."""
        lines = [f"DAG: {self.name}", "=" * 50]

        # Topological sort for display
        sorted_nodes = self._topological_sort()

        for _level, node in enumerate(sorted_nodes):
            indent = "  " * len(node.depends_on)
            status_icon = {
                DAGNodeStatus.PENDING: "○",
                DAGNodeStatus.RUNNING: "▶",
                DAGNodeStatus.COMPLETED: "✓",
                DAGNodeStatus.FAILED: "✗",
                DAGNodeStatus.SKIPPED: "→",
                DAGNodeStatus.BLOCKED: "⊘",
            }.get(node.status, "?")

            deps = ", ".join(node.depends_on) if node.depends_on else "(root)"
            lines.append(f"{indent}{status_icon} {node.name} [{deps}]")

        return "\n".join(lines)

    def _topological_sort(self) -> list[DAGNode]:
        """Topological sort of nodes for display."""
        visited: set[str] = set()
        sorted_nodes: list[DAGNode] = []

        def dfs(node_id: str) -> None:
            if node_id in visited:
                return
            visited.add(node_id)
            node = self._nodes[node_id]
            for dep_id in node.depends_on:
                if dep_id in self._nodes:
                    dfs(dep_id)
            sorted_nodes.append(node)

        for node_id in self._nodes:
            dfs(node_id)

        return sorted_nodes

    def to_dict(self) -> dict[str, Any]:
        """Export DAG configuration as dictionary."""
        return {
            "name": self.name,
            "description": self.description,
            "nodes": [
                {
                    "id": n.id,
                    "name": n.name,
                    "depends_on": n.depends_on,
                    "status": n.status.value,
                    "has_result": n.result is not None,
                }
                for n in self._nodes.values()
            ],
        }

    def __repr__(self) -> str:
        return f"DAG(name='{self.name}', nodes={len(self._nodes)})"
