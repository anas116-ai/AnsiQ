"""Learning module — self-improvement, trajectory learning, and batch training.

Agents can learn from their experiences by recording trajectories,
optimizing their behavior, and running self-improvement cycles.
"""

from ansiq.learning.optimizer import TrajectoryOptimizer
from ansiq.learning.trainer import BatchTrainer, SelfImprover
from ansiq.learning.trajectory import Trajectory, TrajectoryStep

__all__ = [
    "Trajectory",
    "TrajectoryStep",
    "TrajectoryOptimizer",
    "SelfImprover",
    "BatchTrainer",
]
