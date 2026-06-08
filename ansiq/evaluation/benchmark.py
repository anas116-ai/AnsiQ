"""Benchmark Runner — run standardized tests on agents and measure quality.

Features:
- Define benchmark tasks with expected outputs
- Run against multiple agent configurations
- Measure accuracy, speed, cost, and consistency
- Track historical results for trend analysis
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class BenchmarkTask(BaseModel):
    """A single benchmark test case."""

    id: str = Field(default_factory=lambda: f"bench_{uuid.uuid4().hex[:8]}")
    name: str
    description: str = ""

    prompt: str
    """The input prompt for the agent."""

    expected_keywords: list[str] = Field(default_factory=list)
    """Keywords that should appear in the output."""

    expected_patterns: list[str] = Field(default_factory=list)
    """Regex patterns that should match in the output."""

    negative_keywords: list[str] = Field(default_factory=list)
    """Keywords that should NOT appear in the output."""

    max_length: int | None = None
    """Maximum acceptable output length."""

    min_length: int | None = None
    """Minimum acceptable output length."""

    scoring_fn: Callable[[str], float] | None = None
    """Custom scoring function (0.0 to 1.0)."""

    context: str = ""
    """Optional context to provide alongside the prompt."""

    tags: list[str] = Field(default_factory=list)
    """Categorization tags (e.g., ['reasoning', 'code'])."""

    timeout: float = 60.0
    """Maximum execution time for this task."""


class BenchmarkResult(BaseModel):
    """Result of running a single benchmark task."""

    task_id: str
    task_name: str

    # Execution
    output: str = ""
    success: bool = False
    error: str | None = None
    execution_time: float = 0.0

    # Scores
    accuracy_score: float = 0.0
    """0.0 to 1.0 — based on keyword/pattern matching."""

    quality_score: float = 0.0
    """0.0 to 1.0 — from custom scoring function."""

    speed_score: float = 0.0
    """0.0 to 1.0 — based on execution time."""

    overall_score: float = 0.0
    """Weighted combination of all scores."""

    # Cost
    tokens_used: int = 0
    cost_usd: float = 0.0
    model: str = ""

    # Details
    keywords_found: list[str] = Field(default_factory=list)
    keywords_missing: list[str] = Field(default_factory=list)
    patterns_matched: list[str] = Field(default_factory=list)
    negative_found: list[str] = Field(default_factory=list)


class BenchmarkSuite(BaseModel):
    """A complete benchmark suite with multiple tasks."""

    name: str
    description: str = ""
    tasks: list[BenchmarkTask] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # Aggregated results
    results: list[BenchmarkResult] = Field(default_factory=list)

    @property
    def avg_accuracy(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.accuracy_score for r in self.results) / len(self.results)

    @property
    def avg_quality(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.quality_score for r in self.results) / len(self.results)

    @property
    def avg_overall(self) -> float:
        if not self.results:
            return 0.0
        return sum(r.overall_score for r in self.results) / len(self.results)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        passed = sum(1 for r in self.results if r.overall_score >= 0.6)
        return passed / len(self.results)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.results)


class BenchmarkRunner:
    """Run benchmark suites against agents.

    Usage:
        runner = BenchmarkRunner()

        # Create a benchmark task
        task = BenchmarkTask(
            name="math_test",
            prompt="What is 2 + 2?",
            expected_keywords=["4"],
        )

        # Run against an agent
        result = await runner.run_task(agent, task)
        print(f"Score: {result.overall_score:.2%}")
    """

    def __init__(
        self,
        storage_path: Path | str | None = None,
        accuracy_weight: float = 0.5,
        quality_weight: float = 0.3,
        speed_weight: float = 0.2,
    ):
        self.storage_path = Path(storage_path or Path.home() / ".ansiq" / "benchmarks")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.accuracy_weight = accuracy_weight
        self.quality_weight = quality_weight
        self.speed_weight = speed_weight

        self._history: list[dict[str, Any]] = []
        self._load_history()

    async def run_task(
        self,
        agent: Any,
        task: BenchmarkTask,
    ) -> BenchmarkResult:
        """Run a single benchmark task against an agent.

        Args:
            agent: The agent to test (must have a .run() method)
            task: The benchmark task to execute

        Returns:
            BenchmarkResult with scores and details
        """
        start_time = time.time()
        result = BenchmarkResult(
            task_id=task.id,
            task_name=task.name,
        )

        try:
            # Execute the task
            exec_start = time.time()
            response = await agent.run(
                task=task.prompt,
                context=task.context or None,
            )
            exec_time = time.time() - exec_start

            output = response.content if hasattr(response, "content") else str(response)
            result.output = output
            result.execution_time = exec_time

            # Extract cost info
            if hasattr(response, "usage"):
                result.tokens_used = response.usage.total_tokens
            if hasattr(response, "model"):
                result.model = response.model

            result.success = True

        except Exception as e:
            result.error = str(e)
            result.execution_time = time.time() - start_time
            return result

        # Score the result
        result.accuracy_score = self._score_accuracy(task, output)
        result.quality_score = self._score_quality(task, output)
        result.speed_score = self._score_speed(task, exec_time)
        result.overall_score = (
            result.accuracy_score * self.accuracy_weight
            + result.quality_score * self.quality_weight
            + result.speed_score * self.speed_weight
        )

        # Record to history
        self._record_result(result)

        return result

    async def run_suite(
        self,
        agent: Any,
        suite: BenchmarkSuite,
        parallel: bool = False,
    ) -> BenchmarkSuite:
        """Run an entire benchmark suite against an agent."""
        logger.info(
            "Running benchmark suite '%s' (%d tasks) against agent",
            suite.name,
            len(suite.tasks),
        )

        results = []
        for task in suite.tasks:
            result = await self.run_task(agent, task)
            results.append(result)

            if not result.success:
                logger.warning(
                    "Benchmark task '%s' failed: %s",
                    task.name,
                    result.error,
                )

        suite.results = results

        logger.info(
            "Suite '%s' complete: avg_score=%.2f%%, pass_rate=%.1f%%",
            suite.name,
            suite.avg_overall * 100,
            suite.pass_rate * 100,
        )

        return suite

    def _score_accuracy(self, task: BenchmarkTask, output: str) -> float:
        """Score accuracy based on keyword/pattern matching."""
        if not task.expected_keywords and not task.expected_patterns:
            return 1.0  # No criteria = perfect score

        score = 0.0
        total_criteria = 0

        # Check keywords
        output_lower = output.lower()
        for keyword in task.expected_keywords:
            total_criteria += 1
            if keyword.lower() in output_lower:
                score += 1.0

        # Check patterns
        import re

        for pattern in task.expected_patterns:
            total_criteria += 1
            try:
                if re.search(pattern, output, re.IGNORECASE):
                    score += 1.0
            except re.error:
                pass

        # Check negative keywords (penalty)
        for neg in task.negative_keywords:
            total_criteria += 1
            if neg.lower() in output_lower:
                score -= 0.5  # Penalty for negative match

        # Length checks
        output_len = len(output)
        if task.max_length and output_len > task.max_length:
            score -= 0.3
        if task.min_length and output_len < task.min_length:
            score -= 0.3

        return max(0.0, min(1.0, score / max(total_criteria, 1)))

    def _score_quality(self, task: BenchmarkTask, output: str) -> float:
        """Score quality using custom function or defaults."""
        if task.scoring_fn:
            try:
                return min(1.0, max(0.0, task.scoring_fn(output)))
            except Exception:
                return 0.5

        # Default quality heuristics
        score = 0.5  # Base score

        # Reward reasonable length
        output_len = len(output)
        if 50 < output_len < 2000:
            score += 0.1

        # Reward structure (bullet points, sections)
        if any(marker in output for marker in ["\n-", "\n*", "##", "**"]):
            score += 0.1

        # Reward complete sentences
        sentences = output.split(".")
        if len(sentences) >= 2:
            score += 0.1

        return min(1.0, score)

    def _score_speed(self, task: BenchmarkTask, execution_time: float) -> float:
        """Score speed based on execution time vs timeout."""
        if execution_time <= 0:
            return 1.0

        # Score based on fraction of timeout
        fraction = execution_time / task.timeout
        if fraction <= 0.1:
            return 1.0  # Very fast
        elif fraction <= 0.3:
            return 0.9
        elif fraction <= 0.5:
            return 0.7
        elif fraction <= 0.8:
            return 0.5
        else:
            return max(0.1, 1.0 - fraction)

    def _record_result(self, result: BenchmarkResult) -> None:
        """Record result to history."""
        record = {
            "timestamp": time.time(),
            "task_id": result.task_id,
            "task_name": result.task_name,
            "overall_score": result.overall_score,
            "accuracy_score": result.accuracy_score,
            "quality_score": result.quality_score,
            "speed_score": result.speed_score,
            "execution_time": result.execution_time,
            "model": result.model,
            "tokens_used": result.tokens_used,
            "success": result.success,
        }
        self._history.append(record)

        # Keep last 1000 records
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

        self._save_history()

    def get_history(
        self,
        task_name: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get benchmark history."""
        records = self._history
        if task_name:
            records = [r for r in records if r.get("task_name") == task_name]
        return records[-limit:]

    def detect_regression(
        self,
        task_name: str,
        window: int = 10,
        threshold: float = 0.2,
    ) -> dict[str, Any] | None:
        """Detect performance regression for a specific task.

        Args:
            task_name: Task to check for regression
            window: Number of recent results to compare
            threshold: Score drop that triggers regression alert

        Returns:
            Regression info dict if detected, None if no regression
        """
        recent = [r for r in self._history if r.get("task_name") == task_name and r.get("success")]

        if len(recent) < window + 1:
            return None

        # Compare recent window vs historical average
        historical = recent[:-window]
        recent_window = recent[-window:]

        hist_avg = sum(r["overall_score"] for r in historical) / len(historical)
        recent_avg = sum(r["overall_score"] for r in recent_window) / len(recent_window)

        drop = hist_avg - recent_avg

        if drop >= threshold:
            return {
                "task_name": task_name,
                "historical_avg": round(hist_avg, 4),
                "recent_avg": round(recent_avg, 4),
                "drop": round(drop, 4),
                "threshold": threshold,
                "message": f"Regression detected: score dropped by {drop:.1%}",
            }

        return None

    def _save_history(self) -> None:
        try:
            path = self.storage_path / "history.json"
            path.write_text(json.dumps(self._history[-500:], indent=2))
        except Exception:
            pass

    def _load_history(self) -> None:
        try:
            path = self.storage_path / "history.json"
            if path.exists():
                self._history = json.loads(path.read_text())
        except Exception:
            pass

    def __repr__(self) -> str:
        return f"BenchmarkRunner(history={len(self._history)})"
