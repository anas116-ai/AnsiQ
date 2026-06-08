"""Tests for the Learning / Self-Improvement system."""

from __future__ import annotations

from ansiq.learning.optimizer import TrajectoryOptimizer
from ansiq.learning.trainer import BatchTrainer, SelfImprover
from ansiq.learning.trajectory import Trajectory, TrajectoryStep, TrajectoryStore


class TestTrajectoryStep:
    def test_create_step(self):
        """Test creating a trajectory step."""
        step = TrajectoryStep(
            step_number=1,
            action="search_web",
            reasoning="Need to find information",
            tool_used="web_search",
            success=True,
        )
        assert step.step_number == 1
        assert step.action == "search_web"
        assert step.tool_used == "web_search"

    def test_to_dict(self):
        """Test serializing step to dict."""
        step = TrajectoryStep(step_number=1, action="test")
        d = step.to_dict()
        assert d["step_number"] == 1
        assert d["action"] == "test"


class TestTrajectory:
    def test_create_trajectory(self):
        """Test creating a trajectory."""
        traj = Trajectory(
            task_description="Research AI",
            agent_role="Researcher",
        )
        assert traj.task_description == "Research AI"
        assert traj.trajectory_id is not None
        assert len(traj.steps) == 0

    def test_add_step(self):
        """Test adding a step to trajectory."""
        traj = Trajectory(task_description="Test", agent_role="Tester")
        traj.add_step(
            action="search",
            reasoning="Need data",
            tool_used="web",
            duration_ms=100.0,
        )
        assert len(traj.steps) == 1
        assert traj.steps[0].action == "search"
        assert traj.total_duration_ms == 100.0

    def test_complete(self):
        """Test completing a trajectory."""
        traj = Trajectory(task_description="Test", agent_role="Tester")
        traj.complete(success=True)
        assert traj.overall_success is True
        assert traj.end_time is not None

    def test_get_success_rate(self):
        """Test calculating success rate."""
        traj = Trajectory(task_description="Test", agent_role="Tester")
        assert traj.get_success_rate() == 0.0
        traj.add_step(action="s1", success=True)
        traj.add_step(action="s2", success=False)
        assert traj.get_success_rate() == 0.5

    def test_get_failed_steps(self):
        """Test getting failed steps."""
        traj = Trajectory(task_description="Test", agent_role="Tester")
        traj.add_step(action="s1", success=True)
        traj.add_step(action="s2", success=False)
        failed = traj.get_failed_steps()
        assert len(failed) == 1
        assert failed[0].action == "s2"

    def test_summary(self):
        """Test getting trajectory summary."""
        traj = Trajectory(task_description="Research task", agent_role="Analyst")
        traj.add_step(action="step1", success=True)
        summary = traj.summary()
        assert "Research task" in summary
        assert "Analyst" in summary

    def test_to_dict(self):
        """Test serializing trajectory to dict."""
        traj = Trajectory(task_description="Test", agent_role="Tester")
        traj.add_step(action="step1", success=True)
        traj.complete(success=True)
        d = traj.to_dict()
        assert d["task_description"] == "Test"
        assert d["step_count"] == 1
        assert d["overall_success"] is True


class TestTrajectoryStore:
    def test_save_and_load(self, tmp_path):
        """Test saving and loading a trajectory."""
        store = TrajectoryStore(storage_dir=tmp_path)
        traj = Trajectory(task_description="Test", agent_role="Tester")
        file_path = store.save(traj)

        loaded = store.load(traj.trajectory_id)
        assert loaded is not None
        assert loaded.task_description == "Test"

    def test_load_nonexistent(self, tmp_path):
        """Test loading a non-existent trajectory."""
        store = TrajectoryStore(storage_dir=tmp_path)
        loaded = store.load("nonexistent_id")
        assert loaded is None

    def test_list_trajectories(self, tmp_path):
        """Test listing trajectories."""
        store = TrajectoryStore(storage_dir=tmp_path)
        traj1 = Trajectory(task_description="Task 1", agent_role="A")
        traj2 = Trajectory(task_description="Task 2", agent_role="B")
        store.save(traj1)
        store.save(traj2)

        listing = store.list_trajectories()
        assert len(listing) >= 2

    def test_get_stats(self, tmp_path):
        """Test getting store stats."""
        store = TrajectoryStore(storage_dir=tmp_path)
        traj = Trajectory(task_description="Test", agent_role="Tester")
        traj.complete(success=True)
        store.save(traj)

        stats = store.get_stats()
        assert stats["total_trajectories"] >= 1
        assert stats["successful"] >= 1


class TestTrajectoryOptimizer:
    def test_no_data(self, tmp_path):
        """Test optimizer with no data."""
        store = TrajectoryStore(storage_dir=tmp_path)
        optimizer = TrajectoryOptimizer(store=store)
        patterns = optimizer.analyze_success_patterns(limit=10)
        assert patterns.get("status") == "no_data"

    def test_extract_lessons_no_data(self, tmp_path):
        """Test extracting lessons with no data."""
        store = TrajectoryStore(storage_dir=tmp_path)
        optimizer = TrajectoryOptimizer(store=store)
        lessons = optimizer.extract_lessons(limit=10)
        assert len(lessons) >= 1
        assert "No trajectories" in lessons[0]

    def test_get_optimization_suggestions(self):
        """Test getting optimization suggestions."""
        optimizer = TrajectoryOptimizer()
        traj = Trajectory(task_description="Test", agent_role="Tester")
        traj.add_step(action="step1", success=False)
        traj.add_step(action="step2", success=True)

        suggestions = optimizer.get_optimization_suggestions(traj)
        assert isinstance(suggestions, list)


class TestSelfImprover:
    def test_create(self, tmp_path):
        """Test creating a self improver."""
        store = TrajectoryStore(storage_dir=tmp_path)
        improver = SelfImprover(trajectory_store=store)
        assert improver.improvement_cycles == 0

    def test_run_improvement_cycle(self, tmp_path):
        """Test running an improvement cycle."""
        store = TrajectoryStore(storage_dir=tmp_path)
        improver = SelfImprover(trajectory_store=store)

        import asyncio
        report = asyncio.run(improver.run_improvement_cycle())
        assert report["cycle"] == 1

    def test_get_report(self):
        """Test getting improvement report."""
        improver = SelfImprover()
        report = improver.get_improvement_report()
        assert report["total_cycles"] == 0


class TestBatchTrainer:
    def test_create(self, tmp_path):
        """Test creating a batch trainer."""
        store = TrajectoryStore(storage_dir=tmp_path)
        trainer = BatchTrainer(trajectory_store=store)
        assert trainer is not None

    def test_train_no_data(self, tmp_path):
        """Test training with no data."""
        store = TrajectoryStore(storage_dir=tmp_path)
        trainer = BatchTrainer(trajectory_store=store)

        import asyncio
        result = asyncio.run(trainer.train(n_iterations=2))
        assert result["total_iterations"] == 2
        assert len(result["iterations"]) == 2

    def test_get_stats(self, tmp_path):
        """Test getting training data stats."""
        store = TrajectoryStore(storage_dir=tmp_path)
        trainer = BatchTrainer(trajectory_store=store)
        stats = trainer.get_training_data_stats()
        assert "total_trajectories" in stats
