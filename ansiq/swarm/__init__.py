"""Swarm Intelligence — multi-agent collaboration with voting, debating, and consensus."""

from ansiq.swarm.consensus import ConsensusEngine, ConsensusMethod
from ansiq.swarm.debate import DebateEngine, DebateResult, DebateRound
from ansiq.swarm.intelligence import (
    AgentOpinion,
    ConsensusResult,
    SwarmConfig,
    SwarmIntelligence,
    VoteType,
)

__all__ = [
    "SwarmIntelligence",
    "SwarmConfig",
    "AgentOpinion",
    "ConsensusResult",
    "VoteType",
    "ConsensusEngine",
    "ConsensusMethod",
    "DebateEngine",
    "DebateRound",
    "DebateResult",
]
