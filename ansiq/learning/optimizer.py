"""Trajectory Optimizer — analyzes trajectories to improve agent behavior.

Identifies patterns in successful vs failed trajectories:
- Which actions lead to success?
- Where do agents commonly fail?
- What tools are most effective?
- Optimal step ordering
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Any

from ansiq.learning.trajectory import Trajectory, TrajectoryStore

logger = logging.getLogger(__name__)


class TrajectoryOptimizer:
    """Analyzes trajectories to extract learning signals.

    Provides insights that the SelfImprover can use to
    adjust agent behavior.
    """

    def __init__(self, store: TrajectoryStore | None = None):
        self.store = store or TrajectoryStore()

    def analyze_success_patterns(self, limit: int = 100) -> dict[str, Any]:
        """Analyze what patterns lead to successful outcomes."""
        trajectories = self.store.list_trajectories(limit=limit)
        if not trajectories:
            return {"status": "no_data"}

        successful_steps: list[str] = []
        failed_steps: list[str] = []
        successful_agents: Counter = Counter()
        successful_tools: Counter = Counter()
        failed_tools: Counter = Counter()

        for t_info in trajectories:
            traj = self.store.load(t_info.get("trajectory_id", ""))
            if not traj:
                continue

            if traj.overall_success:
                successful_agents[traj.agent_role] += 1
                for step in traj.steps:
                    successful_steps.append(step.action)
                    if step.tool_used:
                        successful_tools[step.tool_used] += 1
            else:
                for step in traj.steps:
                    failed_steps.append(step.action)
                    if step.tool_used:
                        failed_tools[step.tool_used] += 1

        return {
            "total_analyzed": len(trajectories),
            "common_successful_actions": successful_steps[:10],
            "common_failed_actions": failed_steps[:10],
            "best_tools": dict(successful_tools.most_common(5)),
            "worst_tools": dict(failed_tools.most_common(5)),
            "best_agents": dict(successful_agents.most_common(5)),
        }

    def extract_lessons(self, limit: int = 50) -> list[str]:
        """Extract actionable lessons from trajectory analysis.

        Returns a list of insights like:
        - "Using tool X increases success rate by Y%"
        - "Step Z is a common failure point"
        """
        patterns = self.analyze_success_patterns(limit=limit)
        lessons: list[str] = []

        if patterns.get("status") == "no_data":
            return ["No trajectories available for analysis yet."]

        if patterns.get("best_tools"):
            best_tool, best_count = list(patterns["best_tools"].items())[0]
            lessons.append(f"Tool '{best_tool}' was used in {best_count} successful trajectories.")

        if patterns.get("worst_tools"):
            worst_tool = list(patterns["worst_tools"].keys())[0]
            lessons.append(
                f"Tool '{worst_tool}' appears frequently in failed trajectories. Consider reviewing its usage."
            )

        if patterns.get("best_agents"):
            best_agent = list(patterns["best_agents"].keys())[0]
            lessons.append(f"Agent role '{best_agent}' has the highest success rate.")

        return lessons

    def get_optimization_suggestions(
        self,
        trajectory: Trajectory,
    ) -> list[str]:
        """Get specific optimization suggestions for a trajectory."""
        suggestions: list[str] = []

        failed_steps = trajectory.get_failed_steps()
        if failed_steps:
            suggestions.append(
                f"Review failed steps: {', '.join(s.action[:50] for s in failed_steps[:3])}"
            )

        # Check step ordering
        for i, step in enumerate(trajectory.steps[:-1]):
            next_step = trajectory.steps[i + 1]
            if not step.success and next_step.success:
                suggestions.append(
                    f"Step '{step.action[:50]}' failed but '{next_step.action[:50]}' "
                    f"succeeded — investigate if step is necessary."
                )

        # Check for repeated actions
        actions = [s.action for s in trajectory.steps]
        if len(actions) != len(set(actions)):
            suggestions.append("Repeated actions detected — consider deduplication.")

        return suggestions
