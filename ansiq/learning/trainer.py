"""Self-Improver and Batch Trainer — autonomous agent improvement.

Inspired by Hermes Agent's self-improvement capabilities:
1. SelfImprover: runs improvement cycles using trajectory analysis
2. BatchTrainer: trains from historical execution data

All code is original — no copy from Hermes or CrewAI.
"""

from __future__ import annotations

import logging
from typing import Any

from ansiq.learning.optimizer import TrajectoryOptimizer
from ansiq.learning.trajectory import TrajectoryStore
from ansiq.skills.learner import SkillLearner

logger = logging.getLogger(__name__)


class SelfImprover:
    """Autonomous self-improvement system.

    Runs improvement cycles:
    1. Load recent trajectories
    2. Analyze success/failure patterns
    3. Generate insights
    4. Create/improve skills based on lessons learned
    5. Update agent behavior
    """

    def __init__(
        self,
        trajectory_store: TrajectoryStore | None = None,
        optimizer: TrajectoryOptimizer | None = None,
        skill_learner: SkillLearner | None = None,
    ):
        self.trajectory_store = trajectory_store or TrajectoryStore()
        self.optimizer = optimizer or TrajectoryOptimizer(self.trajectory_store)
        self.skill_learner = skill_learner or SkillLearner()
        self.improvement_cycles: int = 0
        self.lessons_learned: list[str] = []

    async def run_improvement_cycle(
        self,
        llm: Any | None = None,
        limit_trajectories: int = 50,
    ) -> dict[str, Any]:
        """Run one improvement cycle.

        Returns a report of what was learned and changed.
        """
        self.improvement_cycles += 1
        logger.info(
            "Starting improvement cycle %d",
            self.improvement_cycles,
        )

        # 1. Analyze trajectories
        patterns = self.optimizer.analyze_success_patterns(limit=limit_trajectories)

        # 2. Extract lessons
        lessons = self.optimizer.extract_lessons(limit=limit_trajectories)
        self.lessons_learned.extend(lessons)

        # 3. Create improvement skills from lessons
        skills_created = 0
        for lesson in lessons[:3]:  # Create at most 3 skills per cycle
            if llm and self.skill_learner:
                try:
                    skill_name = f"improvement_{self.improvement_cycles}_{skills_created}"
                    await self.skill_learner.create_skill(
                        name=skill_name,
                        description=lesson[:200],
                        category="self-improvement",
                        llm=llm,
                    )
                    skills_created += 1
                except Exception as e:
                    logger.warning("Failed to create improvement skill: %s", e)

        return {
            "cycle": self.improvement_cycles,
            "patterns_analyzed": patterns.get("total_analyzed", 0),
            "lessons_extracted": len(lessons),
            "skills_created": skills_created,
            "lessons": lessons,
        }

    def get_improvement_report(self) -> dict[str, Any]:
        """Get a summary of all improvements made."""
        return {
            "total_cycles": self.improvement_cycles,
            "lessons_learned": self.lessons_learned[-20:],
            "total_lessons": len(self.lessons_learned),
        }


class BatchTrainer:
    """Trains agents from historical execution data.

    Unlike traditional ML training, this "trains" by:
    - Analyzing past trajectories
    - Identifying optimal patterns
    - Generating improved skill implementations
    - Building a knowledge base of "what works"

    Inspired by CrewAI's train CLI and Hermes Agent's batch training,
    but implemented as a pure learning-from-experience system.
    """

    def __init__(
        self,
        trajectory_store: TrajectoryStore | None = None,
        optimizer: TrajectoryOptimizer | None = None,
    ):
        self.trajectory_store = trajectory_store or TrajectoryStore()
        self.optimizer = optimizer or TrajectoryOptimizer(self.trajectory_store)

    async def train(
        self,
        n_iterations: int = 5,
        llm: Any | None = None,
    ) -> dict[str, Any]:
        """Run training for N iterations.

        Each iteration:
        1. Loads trajectories
        2. Analyzes patterns
        3. Generates improvements
        4. Records training results
        """
        results = []
        for i in range(n_iterations):
            logger.info("Training iteration %d/%d", i + 1, n_iterations)

            patterns = self.optimizer.analyze_success_patterns()
            lessons = self.optimizer.extract_lessons()

            iteration_result = {
                "iteration": i + 1,
                "trajectories_analyzed": patterns.get("total_analyzed", 0),
                "lessons": lessons,
                "best_tools": patterns.get("best_tools", {}),
            }
            results.append(iteration_result)

        return {
            "total_iterations": n_iterations,
            "iterations": results,
            "summary": self._generate_training_summary(results),
        }

    def _generate_training_summary(self, results: list[dict[str, Any]]) -> str:
        """Generate a human-readable training summary."""
        if not results:
            return "No training data available."

        lines = ["## Training Summary\n"]
        for r in results:
            lines.append(f"Iteration {r['iteration']}:")
            lines.append(f"  - Analyzed {r['trajectories_analyzed']} trajectories")
            if r.get("lessons"):
                lines.append(f"  - Extracted {len(r['lessons'])} lessons")
                for lesson in r["lessons"][:2]:
                    lines.append(f"    • {lesson[:100]}")
        return "\n".join(lines)

    def get_training_data_stats(self) -> dict[str, Any]:
        """Get statistics about available training data."""
        return self.trajectory_store.get_stats()
