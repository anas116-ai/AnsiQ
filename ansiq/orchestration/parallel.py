"""Parallel Executor — execute multiple tasks concurrently with resource limits.

Provides:
- TaskGroup: group related tasks for concurrent execution
- ParallelExecutor: manage multiple task groups with resource caps
- BatchProcessor: process items in parallel batches
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class TaskGroup(BaseModel):
    """A group of related tasks executed as a unit.

    All tasks in a group run concurrently. The group completes
    when all tasks complete (or any fails if strict=True).
    """

    name: str
    tasks: list[Callable[[], Awaitable[Any]]] = Field(default_factory=list)
    strict: bool = False
    """If True, first failure cancels all remaining tasks in group."""

    timeout: float | None = None
    """Maximum time for the entire group."""

    max_concurrent: int = 10
    """Maximum concurrent tasks within this group."""

    results: list[Any] = Field(default_factory=list, exclude=True)
    errors: list[str] = Field(default_factory=list, exclude=True)

    model_config = {"arbitrary_types_allowed": True}

    def add(self, task: Callable[[], Awaitable[Any]]) -> TaskGroup:
        """Add a task to the group."""
        self.tasks.append(task)
        return self

    async def execute(self) -> list[Any]:
        """Execute all tasks in the group concurrently."""
        semaphore = asyncio.Semaphore(self.max_concurrent)
        self.results = []
        self.errors = []

        async def _run(task: Callable[[], Awaitable[Any]]) -> Any:
            async with semaphore:
                try:
                    result = await task()
                    self.results.append(result)
                    return result
                except Exception as e:
                    self.errors.append(str(e))
                    if self.strict:
                        raise
                    return None

        tasks = [_run(t) for t in self.tasks]

        if self.timeout:
            try:
                done, _ = await asyncio.wait(
                    tasks,
                    timeout=self.timeout,
                    return_when=(asyncio.FIRST_EXCEPTION if self.strict else asyncio.ALL_COMPLETED),
                )
                # Cancel remaining
                for task in tasks:
                    if not task.done():
                        task.cancel()
            except TimeoutError:
                logger.warning("TaskGroup '%s' timed out after %ss", self.name, self.timeout)
        else:
            await asyncio.gather(*tasks, return_exceptions=not self.strict)

        return self.results


class BatchProcessor:
    """Process items in parallel batches with controlled concurrency.

    Useful for processing large lists of items (e.g., search queries,
    document chunks, etc.) with rate limiting.

    Usage:
        processor = BatchProcessor(max_concurrent=5)
        results = await processor.process(
            items=["item1", "item2", ...],
            handler=lambda item: process_item(item)
        )
    """

    def __init__(
        self,
        max_concurrent: int = 10,
        rate_limit: float | None = None,
        retry_count: int = 0,
        retry_delay: float = 1.0,
    ):
        self.max_concurrent = max_concurrent
        self.rate_limit = rate_limit
        self.retry_count = retry_count
        self.retry_delay = retry_delay

        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._last_request_time: float = 0
        self._lock = asyncio.Lock()

    async def _rate_limit_wait(self) -> None:
        """Wait if needed to respect rate limit."""
        if self.rate_limit is None:
            return

        async with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < self.rate_limit:
                wait_time = self.rate_limit - elapsed
                await asyncio.sleep(wait_time)
            self._last_request_time = time.time()

    async def process(
        self,
        items: list[Any],
        handler: Callable[[Any], Awaitable[Any]],
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> list[Any]:
        """Process all items in parallel batches.

        Args:
            items: List of items to process
            handler: Async function that processes a single item
            progress_callback: Called with (completed, total) after each item

        Returns:
            List of results (in original order)
        """
        total = len(items)
        results: list[Any] = [None] * total
        completed = 0

        async def process_item(index: int, item: Any) -> None:
            nonlocal completed

            async with self._semaphore:
                await self._rate_limit_wait()

                for attempt in range(self.retry_count + 1):
                    try:
                        result = await handler(item)
                        results[index] = result
                        break
                    except Exception as e:
                        if attempt < self.retry_count:
                            logger.warning(
                                "Item %d/%d failed (attempt %d/%d): %s",
                                index + 1,
                                total,
                                attempt + 1,
                                self.retry_count + 1,
                                e,
                            )
                            await asyncio.sleep(self.retry_delay)
                        else:
                            logger.error(
                                "Item %d/%d failed after %d attempts: %s",
                                index + 1,
                                total,
                                self.retry_count + 1,
                                e,
                            )
                            results[index] = e

                completed += 1
                if progress_callback:
                    progress_callback(completed, total)

        # Launch all tasks
        tasks = [process_item(i, item) for i, item in enumerate(items)]
        await asyncio.gather(*tasks, return_exceptions=True)

        return results

    async def process_stream(
        self,
        items: list[Any],
        handler: Callable[[Any], Awaitable[Any]],
    ) -> AsyncIterator[tuple[int, Any]]:
        """Process items and yield results as they complete.

        Yields (index, result) tuples as each item completes.
        Useful for showing real-time progress in UIs.
        """
        total = len(items)
        results: list[Any] = [None] * total

        async def process_item(index: int, item: Any) -> tuple[int, Any]:
            async with self._semaphore:
                await self._rate_limit_wait()

                for attempt in range(self.retry_count + 1):
                    try:
                        result = await handler(item)
                        results[index] = result
                        return (index, result)
                    except Exception as e:
                        if attempt < self.retry_count:
                            await asyncio.sleep(self.retry_delay)
                        else:
                            results[index] = e
                            return (index, e)

        tasks = {process_item(i, item): i for i, item in enumerate(items)}

        for coro in asyncio.as_completed(tasks):
            try:
                idx, result = await coro
                yield (idx, result)
            except Exception as e:
                idx = tasks.get(coro, -1)
                yield (idx, e)


class ParallelExecutor:
    """High-level parallel executor for agent tasks.

    Manages multiple TaskGroups with resource limits.
    Integrates with AnsiQ's Crew and Agent systems.

    Usage:
        executor = ParallelExecutor(max_workers=10)

        # Create task groups
        group1 = TaskGroup(name="research", strict=False)
        group1.add(lambda: agent1.run("Search topic A"))
        group1.add(lambda: agent2.run("Search topic B"))

        group2 = TaskGroup(name="synthesis", strict=True)
        group2.add(lambda: agent3.run("Synthesize results"))

        # Execute
        results = await executor.execute_groups([group1, group2])
    """

    def __init__(
        self,
        max_workers: int = 10,
        default_timeout: float | None = None,
    ):
        self.max_workers = max_workers
        self.default_timeout = default_timeout
        self._stats: dict[str, Any] = {
            "total_groups": 0,
            "total_tasks": 0,
            "failed_tasks": 0,
            "total_time": 0.0,
        }

    async def execute_groups(
        self,
        groups: list[TaskGroup],
        sequential: bool = False,
    ) -> list[list[Any]]:
        """Execute multiple task groups.

        Args:
            groups: List of TaskGroups to execute
            sequential: If True, execute groups sequentially (not in parallel)

        Returns:
            List of results from each group
        """
        start_time = time.time()
        all_results: list[list[Any]] = []

        self._stats["total_groups"] += len(groups)
        self._stats["total_tasks"] += sum(len(g.tasks) for g in groups)

        if sequential:
            for group in groups:
                logger.info("Executing group '%s' (%d tasks)", group.name, len(group.tasks))
                results = await group.execute()
                all_results.append(results)
        else:
            logger.info("Executing %d groups in parallel", len(groups))

            async def execute_group(group: TaskGroup) -> tuple[str, list[Any]]:
                results = await group.execute()
                return (group.name, results)

            tasks = [execute_group(g) for g in groups]
            completed = await asyncio.gather(*tasks, return_exceptions=True)

            for item in completed:
                if isinstance(item, Exception):
                    logger.error("Group execution failed: %s", item)
                    all_results.append([])
                else:
                    name, results = item
                    all_results.append(results)

        # Stats
        total_time = time.time() - start_time
        self._stats["total_time"] += total_time
        failed = sum(1 for r in all_results for item in r if isinstance(item, Exception))
        self._stats["failed_tasks"] += failed

        logger.info(
            "Parallel execution complete: %d groups, %d tasks, %.2fs",
            len(groups),
            sum(len(r) for r in all_results),
            total_time,
        )

        return all_results

    def get_stats(self) -> dict[str, Any]:
        """Get execution statistics."""
        return {**self._stats}

    def reset_stats(self) -> None:
        """Reset execution statistics."""
        self._stats = {
            "total_groups": 0,
            "total_tasks": 0,
            "failed_tasks": 0,
            "total_time": 0.0,
        }
