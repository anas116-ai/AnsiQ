"""Quality Metrics — structured quality measurements for agent outputs.

Provides:
- QualityMetrics: compute accuracy, relevance, coherence scores
- MetricResult: individual metric measurement
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel


class MetricResult(BaseModel):
    """A single metric measurement."""

    name: str
    score: float = 0.0
    """0.0 to 1.0 quality score."""

    weight: float = 1.0
    details: str = ""

    @property
    def grade(self) -> str:
        if self.score >= 0.9:
            return "A+"
        elif self.score >= 0.8:
            return "A"
        elif self.score >= 0.7:
            return "B"
        elif self.score >= 0.6:
            return "C"
        elif self.score >= 0.4:
            return "D"
        else:
            return "F"


class QualityMetrics:
    """Compute quality metrics for agent outputs.

    Usage:
        metrics = QualityMetrics()
        result = metrics.evaluate(
            output="Python is a high-level programming language...",
            task_description="Explain Python",
            expected_keywords=["programming", "language"],
        )
        print(f"Overall: {result['overall_score']:.2%}")
    """

    def evaluate(
        self,
        output: str,
        task_description: str = "",
        expected_keywords: list[str] | None = None,
        negative_keywords: list[str] | None = None,
        min_length: int = 10,
        max_length: int = 5000,
        context: str = "",
    ) -> dict[str, Any]:
        """Compute comprehensive quality metrics for an output."""
        results: list[MetricResult] = []

        results.append(
            self._accuracy_score(output, expected_keywords or [], negative_keywords or [])
        )
        results.append(self._relevance_score(output, task_description))
        results.append(self._coherence_score(output))
        results.append(self._completeness_score(output, task_description, expected_keywords or []))
        results.append(self._format_score(output))

        weighted_sum = sum(r.score * r.weight for r in results)
        total_weight = sum(r.weight for r in results)
        overall = weighted_sum / total_weight if total_weight > 0 else 0.0

        return {
            "overall_score": round(overall, 4),
            "metrics": {
                r.name: {"score": r.score, "grade": r.grade, "weight": r.weight} for r in results
            },
            "details": [r.details for r in results if r.details],
        }

    def _accuracy_score(
        self, output: str, expected: list[str], negative: list[str]
    ) -> MetricResult:
        """Score based on keyword presence/absence."""
        if not expected:
            score = 1.0
        else:
            output_lower = output.lower()
            found = sum(1 for kw in expected if kw.lower() in output_lower)
            penalty = sum(0.5 for kw in negative if kw.lower() in output_lower)
            score = max(0.0, (found / max(len(expected), 1)) - penalty)

        return MetricResult(
            name="accuracy",
            score=min(1.0, score),
            weight=1.0,
            details=f"Found {sum(1 for kw in expected if kw.lower() in output.lower())}/{len(expected)} expected keywords",
        )

    def _relevance_score(self, output: str, task: str) -> MetricResult:
        """Score based on task-output relevance."""
        if not task:
            return MetricResult(name="relevance", score=1.0, weight=0.8)

        if not output:
            return MetricResult(
                name="relevance",
                score=0.0,
                weight=0.8,
                details="Empty output",
            )

        task_words = set(task.lower().split())
        if not task_words:
            return MetricResult(name="relevance", score=1.0, weight=0.8)

        output_words = set(output.lower().split())
        overlap = len(task_words & output_words)
        # Scale so ~30% overlap yields a perfect score. Guard against /0.
        denominator = max(len(task_words) * 0.3, 1)
        score = min(1.0, overlap / denominator)

        return MetricResult(
            name="relevance",
            score=score,
            weight=0.8,
            details=f"Word overlap: {overlap}/{len(task_words)} task words",
        )

    def _coherence_score(self, output: str) -> MetricResult:
        """Score based on structural coherence."""
        score = 0.5

        sentences = [s.strip() for s in output.split(".") if s.strip()]
        if len(sentences) >= 2:
            score += 0.2
        if len(sentences) >= 4:
            score += 0.1

        paragraphs = [p.strip() for p in output.split("\n\n") if p.strip()]
        if len(paragraphs) >= 2:
            score += 0.1

        if output.startswith(("#", "-", "*", "```")):
            score += 0.1

        return MetricResult(
            name="coherence",
            score=min(1.0, score),
            weight=0.7,
            details=f"{len(sentences)} sentences, {len(paragraphs)} paragraphs",
        )

    def _completeness_score(self, output: str, task: str, keywords: list[str]) -> MetricResult:
        """Score based on how complete the answer is."""
        score = 0.5
        output_len = len(output)

        if output_len > 200:
            score += 0.2
        if output_len > 500:
            score += 0.1
        if output_len > 1000:
            score += 0.1

        if keywords:
            output_lower = output.lower()
            covered = sum(1 for kw in keywords if kw.lower() in output_lower)
            score += 0.1 * (covered / len(keywords))

        return MetricResult(
            name="completeness",
            score=min(1.0, score),
            weight=0.6,
            details=f"Output length: {output_len} chars",
        )

    def _format_score(self, output: str) -> MetricResult:
        """Score based on formatting quality."""
        score = 0.5

        if re.search(r"\*\*.*?\*\*", output):
            score += 0.15
        if re.search(r"^#{1,3}\s", output, re.MULTILINE):
            score += 0.15
        if re.search(r"^\s*[-*]\s", output, re.MULTILINE):
            score += 0.1
        if "```" in output:
            score += 0.1

        return MetricResult(
            name="formatting",
            score=min(1.0, score),
            weight=0.3,
            details="Markdown formatting detected" if score > 0.6 else "Minimal formatting",
        )
