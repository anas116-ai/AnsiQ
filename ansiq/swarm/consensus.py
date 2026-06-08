"""Consensus Engine — algorithms for reaching agreement between agents.

Multiple consensus methods:
- MAJORITY: Simple majority vote
- WEIGHTED: Weighted by agent confidence/reputation
- BORDA: Ranked-choice voting
- CONSENSUS: Iterative until agreement threshold met
"""

from __future__ import annotations

import logging
from enum import StrEnum
from typing import Any

from ansiq.swarm.intelligence import AgentOpinion, VoteType

logger = logging.getLogger(__name__)


class ConsensusMethod(StrEnum):
    """Available consensus methods."""

    MAJORITY = "majority"
    """Simple majority vote wins."""

    WEIGHTED = "weighted"
    """Votes weighted by agent confidence."""

    BORDA = "borda"
    """Ranked-choice voting (Borda count)."""

    SUPERMAJORITY = "supermajority"
    """Requires 2/3 majority."""


class ConsensusEngine:
    """Pluggable consensus engine supporting multiple algorithms.

    Usage:
        engine = ConsensusEngine(method=ConsensusMethod.WEIGHTED)

        opinions = [
            AgentOpinion(agent_name="Alice", vote=VoteType.AGREE, confidence=0.9),
            AgentOpinion(agent_name="Bob", vote=VoteType.DISAGREE, confidence=0.7),
        ]

        winner, confidence = engine.resolve(opinions)
    """

    def __init__(
        self,
        method: ConsensusMethod = ConsensusMethod.WEIGHTED,
        supermajority_threshold: float = 0.667,
        min_votes: int = 1,
    ):
        self.method = method
        self.supermajority_threshold = supermajority_threshold
        self.min_votes = min_votes

    def resolve(
        self,
        opinions: list[AgentOpinion],
    ) -> tuple[VoteType, float, dict[str, Any]]:
        """Resolve a set of opinions into a consensus decision.

        Returns:
            Tuple of (winner_vote, confidence_score, metadata)
        """
        if len(opinions) < self.min_votes:
            return (VoteType.ABSTAIN, 0.0, {"reason": "Not enough votes"})

        if self.method == ConsensusMethod.MAJORITY:
            return self._resolve_majority(opinions)
        elif self.method == ConsensusMethod.WEIGHTED:
            return self._resolve_weighted(opinions)
        elif self.method == ConsensusMethod.BORDA:
            return self._resolve_borda(opinions)
        elif self.method == ConsensusMethod.SUPERMAJORITY:
            return self._resolve_supermajority(opinions)
        else:
            return self._resolve_weighted(opinions)

    def _resolve_majority(
        self,
        opinions: list[AgentOpinion],
    ) -> tuple[VoteType, float, dict[str, Any]]:
        """Simple majority: most votes wins."""
        vote_counts: dict[VoteType, int] = {}

        for op in opinions:
            vote_counts[op.vote] = vote_counts.get(op.vote, 0) + 1

        if not vote_counts:
            return (VoteType.ABSTAIN, 0.0, {"vote_counts": {}})

        winner = max(vote_counts, key=vote_counts.get)
        total = sum(vote_counts.values())
        confidence = vote_counts[winner] / max(total, 1)

        return (
            winner,
            confidence,
            {
                "vote_counts": {k.value: v for k, v in vote_counts.items()},
                "method": "majority",
            },
        )

    def _resolve_weighted(
        self,
        opinions: list[AgentOpinion],
    ) -> tuple[VoteType, float, dict[str, Any]]:
        """Weighted voting: votes weighted by agent confidence."""
        weighted_scores: dict[VoteType, float] = {}
        total_weight = 0.0

        for op in opinions:
            weight = op.confidence
            weighted_scores[op.vote] = weighted_scores.get(op.vote, 0.0) + weight
            total_weight += weight

        if not weighted_scores or total_weight == 0:
            return (VoteType.ABSTAIN, 0.0, {"reason": "No weighted votes"})

        winner = max(weighted_scores, key=weighted_scores.get)
        confidence = weighted_scores[winner] / total_weight

        return (
            winner,
            confidence,
            {
                "weighted_scores": {k.value: round(v, 4) for k, v in weighted_scores.items()},
                "total_weight": round(total_weight, 4),
                "method": "weighted",
            },
        )

    def _resolve_borda(
        self,
        opinions: list[AgentOpinion],
    ) -> tuple[VoteType, float, dict[str, Any]]:
        """Borda count: ranked-choice voting."""
        # In simplified form, count votes with positions
        vote_order = [
            VoteType.STRONGLY_AGREE,
            VoteType.AGREE,
            VoteType.ABSTAIN,
            VoteType.DISAGREE,
            VoteType.STRONGLY_DISAGREE,
        ]

        points = {vote: 0 for vote in vote_order}

        for op in opinions:
            if op.vote in vote_order:
                # Assign points based on position (highest for STRONGLY_AGREE)
                position = vote_order.index(op.vote)
                score = len(vote_order) - position
                points[op.vote] += score * op.confidence

        if not points or max(points.values()) == 0:
            return (VoteType.ABSTAIN, 0.0, {})

        winner = max(points, key=points.get)
        total_points = sum(points.values())
        confidence = points[winner] / max(total_points, 1)

        return (
            winner,
            confidence,
            {
                "borda_points": {k.value: round(v, 2) for k, v in points.items()},
                "method": "borda",
            },
        )

    def _resolve_supermajority(
        self,
        opinions: list[AgentOpinion],
    ) -> tuple[VoteType, float, dict[str, Any]]:
        """Supermajority: requires threshold (default 2/3)."""
        vote_counts: dict[VoteType, int] = {}

        for op in opinions:
            vote_counts[op.vote] = vote_counts.get(op.vote, 0) + 1

        if not vote_counts:
            return (VoteType.ABSTAIN, 0.0, {})

        total = sum(vote_counts.values())
        winner = max(vote_counts, key=vote_counts.get)
        agreement_ratio = vote_counts[winner] / max(total, 1)

        if agreement_ratio >= self.supermajority_threshold:
            confidence = agreement_ratio
        else:
            winner = VoteType.ABSTAIN
            confidence = agreement_ratio

        return (
            winner,
            confidence,
            {
                "vote_counts": {k.value: v for k, v in vote_counts.items()},
                "required_threshold": self.supermajority_threshold,
                "achieved_ratio": round(agreement_ratio, 4),
                "method": "supermajority",
            },
        )

    def __repr__(self) -> str:
        return f"ConsensusEngine(method='{self.method.value}')"
