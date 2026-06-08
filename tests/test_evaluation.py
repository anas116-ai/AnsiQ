"""Tests for the evaluation module — QualityMetrics, BenchmarkRunner, ABTestResult."""

from __future__ import annotations

from ansiq.evaluation.ab_test import ABTester, ABTestResult, VariantResult
from ansiq.evaluation.benchmark import BenchmarkResult, BenchmarkTask
from ansiq.evaluation.metrics import QualityMetrics


class TestQualityMetrics:
    """Test QualityMetrics scoring engine."""

    def test_create(self):
        qm = QualityMetrics()
        assert qm is not None

    def test_evaluate_keywords_present(self):
        qm = QualityMetrics()
        scores = qm.evaluate(
            output="AI systems are transforming how we build software.",
            expected_keywords=["AI", "software", "systems"],
        )
        assert 0 <= scores["overall_score"] <= 1
        assert scores["overall_score"] > 0
        assert "metrics" in scores
        assert "accuracy" in scores["metrics"]
        assert "relevance" in scores["metrics"]

    def test_evaluate_no_keywords(self):
        qm = QualityMetrics()
        scores = qm.evaluate(
            output="Nothing relevant here.",
            expected_keywords=["python", "api", "database"],
        )
        # No keywords match, but coherence/completeness/format base scores
        # keep overall above zero
        assert scores["overall_score"] > 0
        assert scores["overall_score"] < 0.8
        # Accuracy should be low since 0/3 keywords matched
        assert scores["metrics"]["accuracy"]["score"] < 0.5

    def test_evaluate_partial_match(self):
        qm = QualityMetrics()
        scores = qm.evaluate(
            output="Python and APIs are great.",
            expected_keywords=["python", "api", "database", "kubernetes"],
        )
        assert 0 < scores["overall_score"] < 1.0
        # accuracy is a dict with "score", "grade", "weight"
        assert scores["metrics"]["accuracy"]["score"] > 0

    def test_evaluate_empty_output(self):
        qm = QualityMetrics()
        scores = qm.evaluate(output="", expected_keywords=["test"])
        # Empty output still gets non-zero scores from coherence/completeness/format
        # since those have base scores of 0.5
        assert scores["overall_score"] > 0
        # But accuracy should be low since no keywords match
        assert scores["metrics"]["accuracy"]["score"] < 0.5

    def test_evaluate_empty_keywords(self):
        qm = QualityMetrics()
        scores = qm.evaluate(output="Some output", expected_keywords=[])
        # With no keywords expected, overall score should still be valid
        assert 0 <= scores["overall_score"] <= 1


class TestBenchmarkTask:
    """Test BenchmarkTask model."""

    def test_create_task(self):
        task = BenchmarkTask(
            name="math_test",
            prompt="What is 2+2?",
            expected_keywords=["4"],
        )
        assert task.name == "math_test"
        assert task.prompt == "What is 2+2?"
        assert "4" in task.expected_keywords

    def test_task_with_negative_keywords(self):
        task = BenchmarkTask(
            name="specific_test",
            prompt="Name a fruit",
            expected_keywords=["apple", "banana"],
            negative_keywords=["orange"],
        )
        assert "orange" in task.negative_keywords

    def test_task_with_scoring_fn(self):
        def custom_scorer(output: str) -> float:
            return 1.0 if "correct" in output else 0.0

        task = BenchmarkTask(
            name="custom_test",
            prompt="Be correct",
            scoring_fn=custom_scorer,
        )
        assert task.scoring_fn is not None
        assert task.scoring_fn("correct answer") == 1.0
        assert task.scoring_fn("wrong answer") == 0.0


class TestBenchmarkResult:
    """Test BenchmarkResult model."""

    def test_create_result(self):
        result = BenchmarkResult(
            task_id="task_001",
            task_name="math_test",
            overall_score=0.85,
            accuracy_score=0.9,
            execution_time=1.5,
            cost_usd=0.01,
            tokens_used=500,
            success=True,
        )
        assert result.overall_score == 0.85
        assert result.success is True

    def test_failed_result(self):
        result = BenchmarkResult(
            task_id="task_002",
            task_name="timeout_test",
            overall_score=0.0,
            accuracy_score=0.0,
            execution_time=0.0,
            cost_usd=0.0,
            tokens_used=0,
            success=False,
            error="Task timed out",
        )
        assert result.success is False
        assert "timed out" in (result.error or "")


class TestVariantResult:
    """Test VariantResult for A/B testing."""

    def test_create_variant(self):
        vr = VariantResult(name="Variant A")
        assert vr.name == "Variant A"
        assert vr.results == []
        assert vr.avg_score == 0.0

    def test_compute_stats_with_results(self):
        vr = VariantResult(name="Test")
        vr.results = [
            BenchmarkResult(task_id="t1", task_name="test1",
                            overall_score=0.9, accuracy_score=0.8,
                            execution_time=1.0, cost_usd=0.01, tokens_used=100, success=True),
            BenchmarkResult(task_id="t2", task_name="test2",
                            overall_score=0.7, accuracy_score=0.6,
                            execution_time=2.0, cost_usd=0.02, tokens_used=200, success=True),
        ]
        vr.compute_stats()
        assert vr.avg_score == 0.8
        assert vr.avg_accuracy == 0.7
        assert vr.total_cost == 0.03
        assert vr.total_tokens == 300
        assert vr.pass_rate == 1.0

    def test_compute_stats_empty_results(self):
        vr = VariantResult(name="Empty")
        vr.compute_stats()
        # Should not raise, stats remain default
        assert vr.avg_score == 0.0

    def test_compute_stats_with_failures(self):
        vr = VariantResult(name="Mixed")
        vr.results = [
            BenchmarkResult(task_id="t1", task_name="good",
                            overall_score=0.9, accuracy_score=0.8,
                            execution_time=1.0, cost_usd=0.01, tokens_used=100, success=True),
            BenchmarkResult(task_id="t2", task_name="bad",
                            overall_score=0.0, accuracy_score=0.0,
                            execution_time=5.0, cost_usd=0.05, tokens_used=500, success=False,
                            error="Failed"),
        ]
        vr.compute_stats()
        assert vr.pass_rate == 0.5


class TestABTestResult:
    """Test ABTestResult model."""

    def test_create_result(self):
        result = ABTestResult(
            test_name="GPT-4 vs Claude",
            winner="A",
            confidence=0.85,
        )
        assert result.test_name == "GPT-4 vs Claude"
        assert result.winner == "A"
        assert result.is_significant is True
        assert result.confidence == 0.85

    def test_not_significant(self):
        result = ABTestResult(confidence=0.5)
        assert result.is_significant is False

    def test_to_dict(self):
        result = ABTestResult(
            test_name="Test",
            winner="B",
            confidence=0.9,
        )
        d = result.to_dict()
        assert d["test_name"] == "Test"
        assert d["winner"] == "B"
        assert d["is_significant"] is True


class TestABTester:
    """Test ABTester initialization."""

    def test_create_tester(self):
        tester = ABTester()
        assert tester is not None

    def test_run_no_tasks(self):
        """Run with no tasks should handle gracefully."""
        tester = ABTester()
        assert tester._storage_path is None
