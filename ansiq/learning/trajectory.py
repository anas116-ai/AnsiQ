"""Trajectory — records steps taken during task execution for learning.

A trajectory captures the full path an agent took to complete a task,
including the task description, each action taken, the reasoning behind
it, and the outcome. This data is used for self-improvement.

Inspired by Hermes Agent's trajectory learning system,
but built with a cleaner, more structured approach.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TRAJECTORY_DIR = Path.home() / ".ansiq" / "trajectories"


@dataclass
class TrajectoryStep:
    """A single step in a trajectory."""

    step_number: int
    action: str
    reasoning: str = ""
    tool_used: str | None = None
    input_data: str | None = None
    output_data: str | None = None
    success: bool = True
    duration_ms: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_number": self.step_number,
            "action": self.action[:200],
            "reasoning": self.reasoning[:500],
            "tool_used": self.tool_used,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 2),
        }


@dataclass
class Trajectory:
    """Complete record of a task execution journey.

    Used for:
    - Analyzing agent behavior
    - Learning optimal action sequences
    - Identifying failure patterns
    - Self-improvement training
    """

    task_description: str
    agent_role: str
    steps: list[TrajectoryStep] = field(default_factory=list)
    overall_success: bool = True
    total_duration_ms: float = 0.0
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    trajectory_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.trajectory_id is None:
            self.trajectory_id = (
                f"traj_{int(self.start_time)}_{hash(self.task_description) % 10000}"
            )

    def add_step(
        self,
        action: str,
        reasoning: str = "",
        tool_used: str | None = None,
        input_data: str | None = None,
        output_data: str | None = None,
        success: bool = True,
        duration_ms: float = 0.0,
    ) -> TrajectoryStep:
        """Add a step to this trajectory."""
        step = TrajectoryStep(
            step_number=len(self.steps) + 1,
            action=action,
            reasoning=reasoning,
            tool_used=tool_used,
            input_data=input_data,
            output_data=output_data,
            success=success,
            duration_ms=duration_ms,
        )
        self.steps.append(step)
        self.total_duration_ms += duration_ms
        return step

    def complete(self, success: bool = True) -> None:
        """Mark the trajectory as complete."""
        self.overall_success = success
        self.end_time = time.time()

    def get_success_rate(self) -> float:
        """Calculate the success rate of steps."""
        if not self.steps:
            return 0.0
        successful = sum(1 for s in self.steps if s.success)
        return successful / len(self.steps)

    def get_failed_steps(self) -> list[TrajectoryStep]:
        """Get the steps that failed."""
        return [s for s in self.steps if not s.success]

    def summary(self) -> str:
        """Get a human-readable summary."""
        status = "✓" if self.overall_success else "✗"
        return (
            f"[{status}] {self.task_description[:100]}\n"
            f"  Agent: {self.agent_role}\n"
            f"  Steps: {len(self.steps)}, "
            f"Duration: {self.total_duration_ms:.1f}ms, "
            f"Success Rate: {self.get_success_rate():.0%}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "trajectory_id": self.trajectory_id,
            "task_description": self.task_description[:200],
            "agent_role": self.agent_role,
            "overall_success": self.overall_success,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "step_count": len(self.steps),
            "success_rate": self.get_success_rate(),
            "steps": [s.to_dict() for s in self.steps],
            "metadata": self.metadata,
        }


class TrajectoryStore:
    """Persists trajectories to disk for later analysis and training."""

    def __init__(self, storage_dir: Path | str | None = None):
        self.storage_dir = Path(storage_dir or _TRAJECTORY_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, trajectory: Trajectory) -> str:
        """Save a trajectory to disk. Returns the file path."""
        file_path = self.storage_dir / f"{trajectory.trajectory_id}.json"
        data = trajectory.to_dict()
        file_path.write_text(json.dumps(data, indent=2))
        return str(file_path)

    def load(self, trajectory_id: str) -> Trajectory | None:
        """Load a trajectory from disk by ID."""
        file_path = self.storage_dir / f"{trajectory_id}.json"
        if not file_path.exists():
            return None
        try:
            data = json.loads(file_path.read_text())
            traj = Trajectory(
                task_description=data["task_description"],
                agent_role=data["agent_role"],
                overall_success=data.get("overall_success", True),
                total_duration_ms=data.get("total_duration_ms", 0.0),
                trajectory_id=data["trajectory_id"],
            )
            for step_data in data.get("steps", []):
                traj.steps.append(TrajectoryStep(**step_data))
            return traj
        except Exception as e:
            logger.warning("Failed to load trajectory %s: %s", trajectory_id, e)
            return None

    def list_trajectories(self, limit: int = 20) -> list[dict[str, Any]]:
        """List all trajectories with metadata."""
        trajectories = []
        for f in sorted(self.storage_dir.glob("*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text())
                trajectories.append(
                    {
                        "trajectory_id": data.get("trajectory_id", f.stem),
                        "task": data.get("task_description", "")[:80],
                        "success": data.get("overall_success", False),
                        "steps": data.get("step_count", 0),
                        "duration": data.get("total_duration_ms", 0),
                    }
                )
            except Exception:
                continue
        return trajectories

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored trajectories."""
        trajectories = self.list_trajectories(limit=1000)
        total = len(trajectories)
        successful = sum(1 for t in trajectories if t.get("success"))
        return {
            "total_trajectories": total,
            "successful": successful,
            "failed": total - successful,
            "success_rate": round(successful / total, 2) if total else 0,
            "storage_dir": str(self.storage_dir),
        }
