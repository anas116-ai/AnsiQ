"""Reasoning Engine — the "brain" behind every agent action.

Provides structured thinking before execution:
1. Analyze the task
2. Plan steps
3. Execute with reflection
4. Learn from outcomes

This is AnsiQ's unique approach to agent intelligence —
inspired by Hermes Agent's thinking protocol but built
from scratch with a cleaner architecture.
"""

from __future__ import annotations

import json
import logging
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ThoughtType(StrEnum):
    """Types of thinking steps an agent can perform."""

    ANALYSIS = "analysis"
    """Analyzing the task or situation."""

    PLANNING = "planning"
    """Creating a plan of action."""

    REASONING = "reasoning"
    """Logical reasoning about options."""

    REFLECTION = "reflection"
    """Reflecting on past actions or outcomes."""

    DECISION = "decision"
    """Making a choice between options."""

    EXECUTION = "execution"
    """Executing an action."""

    EVALUATION = "evaluation"
    """Evaluating the result of an action."""

    UNCERTAINTY = "uncertainty"
    """Expressing uncertainty or asking for clarification."""


class Thought(BaseModel):
    """A single thinking step in the agent's reasoning process."""

    type: ThoughtType
    content: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    timestamp: float = Field(default_factory=time.time)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_prompt_block(self) -> str:
        """Format thought as a block for LLM prompts."""
        tag = f"[{self.type.value.upper()}]"
        return f"{tag} {self.content}"


class PlanStep(BaseModel):
    """A single step in a plan."""

    step_number: int
    description: str
    agent_role: str | None = None
    tool_name: str | None = None
    expected_outcome: str = ""
    status: str = "pending"
    result: str | None = None
    duration_seconds: float | None = None


class Plan(BaseModel):
    """A complete plan consisting of ordered steps."""

    goal: str
    steps: list[PlanStep] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    completed_at: float | None = None
    overall_status: str = "in_progress"

    def add_step(self, description: str, **kwargs: Any) -> PlanStep:
        """Add a step to the plan."""
        step = PlanStep(
            step_number=len(self.steps) + 1,
            description=description,
            **kwargs,
        )
        self.steps.append(step)
        return step

    def mark_step_complete(self, step_number: int, result: str) -> None:
        """Mark a step as completed with its result."""
        for step in self.steps:
            if step.step_number == step_number:
                step.status = "completed"
                step.result = result
                break

    def get_next_pending_step(self) -> PlanStep | None:
        """Get the next uncompleted step."""
        for step in self.steps:
            if step.status == "pending":
                return step
        return None

    def is_complete(self) -> bool:
        """Check if all steps are completed."""
        return all(step.status == "completed" for step in self.steps)

    def summary(self) -> str:
        """Return a human-readable summary of the plan."""
        lines = [f"Plan: {self.goal[:100]}"]
        for step in self.steps:
            status_mark = "✓" if step.status == "completed" else "○"
            lines.append(f"  {status_mark} Step {step.step_number}: {step.description[:80]}")
        return "\n".join(lines)


class ThinkingProtocol:
    """Configurable thinking protocol for agent reasoning.

    Determines how the agent thinks before acting:
    - minimal: quick thinking, just plan and execute
    - standard: analyze, plan, execute, evaluate
    - deep: analyze, reflect, plan, reason, execute, evaluate, reflect
    """

    MODES = {
        "minimal": ["planning", "execution"],
        "standard": ["analysis", "planning", "execution", "evaluation"],
        "deep": [
            "analysis",
            "reflection",
            "planning",
            "reasoning",
            "execution",
            "evaluation",
            "reflection",
        ],
    }

    def __init__(self, mode: str = "standard"):
        if mode not in self.MODES:
            raise ValueError(
                f"Unknown thinking mode '{mode}'. Choose from: {list(self.MODES.keys())}"
            )
        self.mode = mode
        self.thought_types = self.MODES[mode]

    def should_think(self, thought_type: ThoughtType) -> bool:
        """Check if this thought type should be used in current mode."""
        return thought_type.value in self.thought_types


class ReasoningEngine:
    """The reasoning engine — manages an agent's thinking process.

    Maintains a thought chain, creates plans, and supports
    reflection on outcomes.
    """

    def __init__(
        self,
        protocol: ThinkingProtocol | None = None,
        agent_role: str = "assistant",
    ):
        self.protocol = protocol or ThinkingProtocol("standard")
        self.agent_role = agent_role
        self.thought_chain: list[Thought] = []
        self.current_plan: Plan | None = None
        self.session_insights: list[str] = []

    def think(
        self,
        thought_type: ThoughtType,
        content: str,
        confidence: float = 0.8,
        metadata: dict[str, Any] | None = None,
    ) -> Thought:
        """Add a thinking step to the chain."""
        thought = Thought(
            type=thought_type,
            content=content,
            confidence=confidence,
            metadata=metadata or {},
        )
        self.thought_chain.append(thought)
        logger.debug("Thought [%s]: %s", thought_type.value, content[:80])
        return thought

    def get_recent_thoughts(self, count: int = 5) -> list[Thought]:
        """Get the most recent thinking steps."""
        return self.thought_chain[-count:]

    def get_thought_summary(self) -> str:
        """Get a formatted summary of all thoughts."""
        if not self.thought_chain:
            return ""

        parts = ["## Thinking Process\n"]
        for thought in self.thought_chain:
            parts.append(thought.to_prompt_block())
        return "\n".join(parts)

    async def analyze_task(
        self,
        task: str,
        context: str | None = None,
    ) -> str:
        """Analyze a task and produce a thinking summary.

        This simulates the thinking process that would normally
        be done by the LLM. The actual analysis is performed
        by the agent's LLM provider during execution.
        """
        self.think(
            ThoughtType.ANALYSIS,
            f"Analyzing task: {task[:100]}",
        )

        if self.current_plan:
            self.current_plan = None

        analysis = f"Task: {task}"
        if context:
            analysis += f"\nContext: {context}"
        return analysis

    async def create_plan(
        self,
        goal: str,
        steps: list[str] | None = None,
        llm: Any | None = None,
    ) -> Plan:
        """Create a plan to achieve a goal.

        Can use an LLM to generate steps if not provided.
        """
        self.think(
            ThoughtType.PLANNING,
            f"Creating plan for: {goal[:100]}",
        )

        plan = Plan(goal=goal)

        if steps:
            for _i, step_desc in enumerate(steps, 1):
                plan.add_step(description=step_desc)
        elif llm:
            # Use LLM to generate plan steps
            try:
                from ansiq.llm.base import LLMMessage

                prompt = (
                    f"Create a step-by-step plan to achieve this goal:\n{goal}\n\n"
                    f"Return ONLY a JSON array of step descriptions, no other text:\n"
                    f'["Step 1 description", "Step 2 description", ...]'
                )
                response = await llm.chat(
                    [
                        LLMMessage.system(
                            "You are a planning assistant. Output only valid JSON arrays."
                        ),
                        LLMMessage.user(prompt),
                    ]
                )
                content = response.content.strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                steps_list = json.loads(content)
                for _i, step_desc in enumerate(steps_list, 1):
                    plan.add_step(description=str(step_desc))
            except Exception as e:
                logger.warning("LLM plan generation failed: %s", e)
                plan.add_step(description=f"Execute: {goal[:200]}")

        self.current_plan = plan
        self.think(
            ThoughtType.PLANNING,
            f"Plan created with {len(plan.steps)} steps",
            metadata={"step_count": len(plan.steps)},
        )
        return plan

    async def reflect_on_result(
        self,
        original_task: str,
        result: str,
        success: bool,
    ) -> str:
        """Reflect on the result of an action.

        Generates insights that can be used for future improvement.
        """
        self.think(
            ThoughtType.REFLECTION,
            f"Reflecting on result (success={success})",
            confidence=0.9 if success else 0.5,
        )

        insight = (
            f"Task: {original_task[:80]}\n"
            f"Outcome: {'Success' if success else 'Failed'}\n"
            f"Result: {result[:200]}"
        )
        self.session_insights.append(insight)
        return insight

    def get_session_insights_summary(self) -> str:
        """Get a summary of insights from this session."""
        if not self.session_insights:
            return ""
        parts = ["## Session Insights\n"]
        for i, insight in enumerate(self.session_insights, 1):
            parts.append(f"{i}. {insight[:150]}")
        return "\n".join(parts)

    def reset(self) -> None:
        """Reset the thinking state for a new task."""
        self.thought_chain.clear()
        self.current_plan = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the reasoning state."""
        return {
            "mode": self.protocol.mode,
            "thought_count": len(self.thought_chain),
            "has_plan": self.current_plan is not None,
            "insight_count": len(self.session_insights),
            "recent_thoughts": [
                {"type": t.type.value, "content": t.content[:100]} for t in self.thought_chain[-5:]
            ],
        }
