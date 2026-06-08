"""Tests for the Brain/Reasoning system."""

from __future__ import annotations

import pytest

from ansiq.brain.reasoning import (
    Plan,
    PlanStep,
    ReasoningEngine,
    ThinkingProtocol,
    Thought,
    ThoughtType,
)


class TestThought:
    def test_create_thought(self):
        """Test creating a thought."""
        t = Thought(
            type=ThoughtType.ANALYSIS,
            content="Analyzing the task",
            confidence=0.9,
        )
        assert t.type == ThoughtType.ANALYSIS
        assert t.content == "Analyzing the task"
        assert t.confidence == 0.9

    def test_to_prompt_block(self):
        """Test formatting thought as prompt block."""
        t = Thought(type=ThoughtType.PLANNING, content="Plan the approach")
        block = t.to_prompt_block()
        assert "[PLANNING]" in block
        assert "Plan the approach" in block

    def test_thought_defaults(self):
        """Test Thought default values."""
        t = Thought(type=ThoughtType.REASONING, content="Thinking...")
        assert t.confidence == 0.8
        assert t.timestamp > 0


class TestThinkingProtocol:
    def test_default_mode(self):
        """Test default thinking mode."""
        p = ThinkingProtocol()
        assert p.mode == "standard"
        assert len(p.thought_types) == 4

    def test_minimal_mode(self):
        """Test minimal thinking mode."""
        p = ThinkingProtocol("minimal")
        assert len(p.thought_types) == 2

    def test_deep_mode(self):
        """Test deep thinking mode."""
        p = ThinkingProtocol("deep")
        assert len(p.thought_types) == 7

    def test_invalid_mode(self):
        """Test invalid mode raises error."""
        with pytest.raises(ValueError, match="Unknown thinking mode"):
            ThinkingProtocol("invalid")

    def test_should_think(self):
        """Test should_think checks."""
        p = ThinkingProtocol("minimal")
        assert p.should_think(ThoughtType.PLANNING)
        assert not p.should_think(ThoughtType.ANALYSIS)


class TestPlan:
    def test_create_plan(self):
        """Test creating a plan."""
        plan = Plan(goal="Research AI")
        assert plan.goal == "Research AI"
        assert len(plan.steps) == 0

    def test_add_step(self):
        """Test adding a step to a plan."""
        plan = Plan(goal="Test")
        plan.add_step("Step 1", expected_outcome="Done")
        assert len(plan.steps) == 1
        assert plan.steps[0].step_number == 1
        assert plan.steps[0].description == "Step 1"

    def test_mark_step_complete(self):
        """Test marking a step complete."""
        plan = Plan(goal="Test")
        plan.add_step("Step 1")
        plan.mark_step_complete(1, "Result data")
        assert plan.steps[0].status == "completed"
        assert plan.steps[0].result == "Result data"

    def test_get_next_pending(self):
        """Test getting next pending step."""
        plan = Plan(goal="Test")
        plan.add_step("Step 1")
        plan.add_step("Step 2")
        plan.mark_step_complete(1, "Done")
        next_step = plan.get_next_pending_step()
        assert next_step is not None
        assert next_step.step_number == 2

    def test_is_complete(self):
        """Test checking if plan is complete."""
        plan = Plan(goal="Test")
        plan.add_step("Step 1")
        assert not plan.is_complete()
        plan.mark_step_complete(1, "Done")
        assert plan.is_complete()

    def test_summary(self):
        """Test plan summary."""
        plan = Plan(goal="Research topic")
        plan.add_step("Gather data")
        summary = plan.summary()
        assert "Research topic" in summary
        assert "Gather data" in summary


class TestPlanStep:
    def test_defaults(self):
        """Test PlanStep default values."""
        step = PlanStep(step_number=1, description="Test")
        assert step.status == "pending"
        assert step.result is None
        assert step.duration_seconds is None


class TestReasoningEngine:
    def test_create_engine(self):
        """Test creating a reasoning engine."""
        engine = ReasoningEngine(agent_role="Researcher")
        assert engine.agent_role == "Researcher"
        assert len(engine.thought_chain) == 0

    def test_think(self):
        """Test adding a thought."""
        engine = ReasoningEngine()
        engine.think(ThoughtType.ANALYSIS, "Analyzing", confidence=0.9)
        assert len(engine.thought_chain) == 1
        assert engine.thought_chain[0].type == ThoughtType.ANALYSIS

    def test_get_recent_thoughts(self):
        """Test getting recent thoughts."""
        engine = ReasoningEngine()
        for i in range(10):
            engine.think(ThoughtType.ANALYSIS, f"Thought {i}")
        recent = engine.get_recent_thoughts(count=3)
        assert len(recent) == 3

    def test_get_thought_summary_empty(self):
        """Test empty thought summary."""
        engine = ReasoningEngine()
        assert engine.get_thought_summary() == ""

    def test_get_thought_summary(self):
        """Test thought summary with content."""
        engine = ReasoningEngine()
        engine.think(ThoughtType.ANALYSIS, "Step 1")
        summary = engine.get_thought_summary()
        assert "Thinking Process" in summary
        assert "Step 1" in summary

    def test_analyze_task(self):
        """Test task analysis."""
        engine = ReasoningEngine()
        import asyncio
        analysis = asyncio.run(engine.analyze_task("Research topic"))
        assert "Research topic" in analysis
        assert len(engine.thought_chain) == 1

    def test_create_plan_with_steps(self):
        """Test creating a plan with provided steps."""
        engine = ReasoningEngine()
        import asyncio
        plan = asyncio.run(engine.create_plan("Test", steps=["Step A", "Step B"]))
        assert len(plan.steps) == 2
        assert engine.current_plan is not None

    def test_reflect_on_result(self):
        """Test reflecting on a result."""
        engine = ReasoningEngine()
        import asyncio
        insight = asyncio.run(engine.reflect_on_result("Task", "Good result", True))
        assert "Success" in insight
        assert len(engine.session_insights) == 1

    def test_session_insights_summary_empty(self):
        """Test empty insights summary."""
        engine = ReasoningEngine()
        assert engine.get_session_insights_summary() == ""

    def test_session_insights_summary(self):
        """Test insights summary with content."""
        engine = ReasoningEngine()
        engine.session_insights = ["Learned X", "Learned Y"]
        summary = engine.get_session_insights_summary()
        assert "Session Insights" in summary
        assert "Learned X" in summary

    def test_reset(self):
        """Test resetting the engine."""
        engine = ReasoningEngine()
        engine.think(ThoughtType.ANALYSIS, "Test")
        engine.reset()
        assert len(engine.thought_chain) == 0
        assert engine.current_plan is None

    def test_to_dict(self):
        """Test serialization to dict."""
        engine = ReasoningEngine(agent_role="Researcher")
        d = engine.to_dict()
        assert d["mode"] == "standard"
        assert d["thought_count"] == 0
