"""A/B Tester — compare two agent configurations to find the better one."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ansiq.evaluation.benchmark import BenchmarkResult, BenchmarkTask

logger = logging.getLogger(__name__)


class VariantResult(BaseModel):
    """Results for a single variant (A or B)."""

    name: str
    results: list[BenchmarkResult] = Field(default_factory=list)
    avg_score: float = 0.0
    avg_accuracy: float = 0.0
    avg_speed: float = 0.0
    total_cost: float = 0.0
    total_tokens: int = 0
    pass_rate: float = 0.0

    def compute_stats(self) -> None:
        if not self.results:
            return
        successful = [r for r in self.results if r.success]
        self.avg_score = sum(r.overall_score for r in self.results) / len(self.results)
        self.avg_accuracy = sum(r.accuracy_score for r in self.results) / len(self.results)
        self.avg_speed = sum(r.execution_time for r in self.results) / len(self.results)
        self.total_cost = sum(r.cost_usd for r in self.results)
        self.total_tokens = sum(r.tokens_used for r in self.results)
        self.pass_rate = len(successful) / len(self.results) if self.results else 0


class ABTestResult(BaseModel):
    """Statistical comparison of two agent configurations."""

    test_name: str = ""
    variant_a: VariantResult = Field(default_factory=lambda: VariantResult(name="A"))
    variant_b: VariantResult = Field(default_factory=lambda: VariantResult(name="B"))
    winner: str | None = None
    confidence: float = 0.0
    comparison: dict[str, dict[str, float]] = Field(default_factory=dict)
    recommendation: str = ""

    @property
    def is_significant(self) -> bool:
        return self.confidence >= 0.8

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_name": self.test_name,
            "winner": self.winner,
            "confidence": round(self.confidence, 4),
            "is_significant": self.is_significant,
            "variant_a": {
                "avg_score": round(self.variant_a.avg_score, 4),
                "pass_rate": round(self.variant_a.pass_rate, 4),
                "total_cost": round(self.variant_a.total_cost, 6),
            },
            "variant_b": {
                "avg_score": round(self.variant_b.avg_score, 4),
                "pass_rate": round(self.variant_b.pass_rate, 4),
                "total_cost": round(self.variant_b.total_cost, 6),
            },
            "comparison": self.comparison,
            "recommendation": self.recommendation,
        }


class ABTester:
    """Compare two agents on the same tasks to determine the better configuration.

    Usage:
        tester = ABTester()
        result = await tester.run(
            agent_a=gpt4o_mini_agent,
            agent_b=gpt4o_agent,
            tasks=[BenchmarkTask(name="math", prompt="2+2?", expected_keywords=["4"])],
            test_name="gpt4o-mini vs gpt4o",
        )
        print(f"Winner: {result.winner} (confidence: {result.confidence:.1%})")
    """

    def __init__(self, storage_path: Path | str | None = None) -> None:
        # Lazily created in `run()` to avoid importing the runner at module load
        # and to allow callers to provide a custom storage location.
        self._storage_path = storage_path

    async def run(
        self,
        agent_a: Any,
        agent_b: Any,
        tasks: list[BenchmarkTask],
        test_name: str = "A/B Test",
    ) -> ABTestResult:
        logger.info("Starting A/B test '%s' with %d tasks", test_name, len(tasks))

        # Reuse a single BenchmarkRunner across all tasks so history is consistent
        # and we don't create a new (file-system backed) tracker per task.
        from ansiq.evaluation.benchmark import BenchmarkRunner

        runner = BenchmarkRunner(storage_path=self._storage_path)

        variant_a = VariantResult(name="A")
        for task in tasks:
            result = await runner.run_task(agent_a, task)
            variant_a.results.append(result)

        variant_b = VariantResult(name="B")
        for task in tasks:
            result = await runner.run_task(agent_b, task)
            variant_b.results.append(result)

        variant_a.compute_stats()
        variant_b.compute_stats()

        winner, confidence = self._determine_winner(variant_a, variant_b)
        comparison = self._build_comparison(variant_a, variant_b)
        recommendation = self._generate_recommendation(
            test_name, winner, confidence, variant_a, variant_b, comparison
        )

        return ABTestResult(
            test_name=test_name,
            variant_a=variant_a,
            variant_b=variant_b,
            winner=winner,
            confidence=confidence,
            comparison=comparison,
            recommendation=recommendation,
        )

    def _determine_winner(self, a: VariantResult, b: VariantResult) -> tuple[str | None, float]:
        score_diff = abs(a.avg_score - b.avg_score)
        a_wins = 0
        b_wins = 0
        ties = 0

        for r_a, r_b in zip(a.results, b.results, strict=False):
            if r_a.overall_score > r_b.overall_score:
                a_wins += 1
            elif r_b.overall_score > r_a.overall_score:
                b_wins += 1
            else:
                ties += 1

        total = len(a.results)
        if total == 0:
            return None, 0.0

        # If the average scores are very close AND the win counts are equal,
        # treat the test as inconclusive. Otherwise pick the side with more wins.
        if a_wins == b_wins:
            # No clear winner by majority; tie-break using the average score.
            if score_diff < 0.01:
                return None, 0.0
            return ("A" if a.avg_score > b.avg_score else "B"), 0.5

        if a_wins > b_wins:
            winner = "A"
            consistency = a_wins / total
        else:
            winner = "B"
            consistency = b_wins / total

        # Confidence is the consistency score weighted by the magnitude of the
        # average score difference. Larger score gap → higher confidence.
        confidence = consistency * min(1.0, score_diff * 5 + 0.5)
        return winner, min(1.0, confidence)

    def _build_comparison(self, a: VariantResult, b: VariantResult) -> dict[str, dict[str, float]]:
        metrics = {
            "overall_score": (a.avg_score, b.avg_score),
            "accuracy": (a.avg_accuracy, b.avg_accuracy),
            "speed": (a.avg_speed, b.avg_speed),
            "cost": (a.total_cost, b.total_cost),
            "pass_rate": (a.pass_rate, b.pass_rate),
        }
        comparison = {}
        for metric, (va, vb) in metrics.items():
            delta = vb - va if metric != "speed" else va - vb
            comparison[metric] = {"A": round(va, 4), "B": round(vb, 4), "delta": round(delta, 4)}
        return comparison

    def _generate_recommendation(
        self,
        test_name: str,
        winner: str | None,
        confidence: float,
        a: VariantResult,
        b: VariantResult,
        comparison: dict,
    ) -> str:
        if winner is None:
            return f"Test '{test_name}': No significant difference between A and B."

        score_delta = abs(a.avg_score - b.avg_score)
        parts = [
            f"Test '{test_name}' complete.",
            f"Winner: Variant {winner}",
            f"Score advantage: {score_delta:.1%}",
            f"Confidence: {confidence:.0%}",
        ]

        if confidence >= 0.9:
            parts.append("Verdict: STRONG recommendation")
        elif confidence >= 0.7:
            parts.append("Verdict: Moderate recommendation")
        else:
            parts.append("Verdict: Weak signal - consider more tests")

        if a.total_cost > 0 and b.total_cost > 0:
            cost_ratio = a.total_cost / b.total_cost if b.total_cost > 0 else float("inf")
            if cost_ratio > 2:
                parts.append(f"Cost note: Variant A is {cost_ratio:.1f}x more expensive")
            elif cost_ratio < 0.5:
                parts.append(f"Cost note: Variant B is {1 / cost_ratio:.1f}x more expensive")

        return " ".join(parts)
