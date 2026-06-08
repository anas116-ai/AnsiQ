"""Agent Evaluation Framework — benchmark, test, and improve agents.

Provides:
- BenchmarkRunner: Run standardized agent tests
- QualityMetrics: Accuracy, speed, cost scoring
- ABTester: Compare model configurations
- RegressionDetector: Catch performance drops
"""

from ansiq.evaluation.ab_test import ABTester, ABTestResult
from ansiq.evaluation.benchmark import BenchmarkResult, BenchmarkRunner, BenchmarkTask
from ansiq.evaluation.metrics import MetricResult, QualityMetrics

__all__ = [
    "BenchmarkRunner",
    "BenchmarkResult",
    "BenchmarkTask",
    "QualityMetrics",
    "MetricResult",
    "ABTester",
    "ABTestResult",
]
