"""Tests for the swarm module — SwarmIntelligence, ConsensusEngine, DebateEngine."""

from __future__ import annotations

import pytest

from ansiq.swarm.consensus import ConsensusEngine, ConsensusMethod
from ansiq.swarm.intelligence import (
    AgentOpinion,
    ConsensusResult,
    SwarmConfig,
    SwarmIntelligence,
    VoteType,
)


class TestVoteType:
    """Test VoteType enum."""

    def test_vote_values(self):
        assert VoteType.AGREE.value == "agree"
        assert VoteType.DISAGREE.value == "disagree"
        assert VoteType.ABSTAIN.value == "abstain"
        assert VoteType.STRONGLY_AGREE.value == "strongly_agree"
        assert VoteType.STRONGLY_DISAGREE.value == "strongly_disagree"


class TestAgentOpinion:
    """Test AgentOpinion model."""

    def test_create_opinion(self):
        op = AgentOpinion(
            agent_name="Alice", agent_role="Researcher",
            vote=VoteType.AGREE, reasoning="Good approach", confidence=0.85,
        )
        assert op.agent_name == "Alice"
        assert op.confidence == 0.85

    def test_default_confidence(self):
        op = AgentOpinion(agent_name="Bob", agent_role="Critic", vote=VoteType.DISAGREE)
        assert op.confidence == 0.5

    def test_abstain_default(self):
        op = AgentOpinion(agent_name="Charlie", agent_role="Observer", vote=VoteType.ABSTAIN)
        assert op.vote == VoteType.ABSTAIN


class TestConsensusResult:
    """Test ConsensusResult model."""

    def test_create_result(self):
        result = ConsensusResult(
            topic="Test topic", consensus_answer="We agree",
            confidence=0.8, total_agents=3, agreement_percentage=0.67,
        )
        assert result.topic == "Test topic"
        assert result.consensus_answer == "We agree"
        assert result.total_agents == 3

    def test_default_votes(self):
        result = ConsensusResult(topic="Test", consensus_answer="No opinion")
        assert result.votes == []
        assert result.vote_summary == {}


class TestSwarmConfig:
    """Test SwarmConfig model."""

    def test_defaults(self):
        config = SwarmConfig()
        assert config.rounds == 1
        assert config.require_unanimous is False
        assert config.min_agreement == 0.6
        assert config.weight_by_confidence is True
        assert config.allow_debate is False
        assert config.debate_rounds == 2

    def test_custom_config(self):
        config = SwarmConfig(rounds=3, require_unanimous=True, min_agreement=0.8, allow_debate=True)
        assert config.rounds == 3
        assert config.allow_debate is True


class TestSwarmIntelligence:
    """Test SwarmIntelligence initialization."""

    def test_init_requires_agents(self):
        with pytest.raises(ValueError, match="At least one agent"):
            SwarmIntelligence(agents=[])


class TestConsensusEngine:
    """Test ConsensusEngine consensus algorithms."""

    def test_create_engine(self):
        engine = ConsensusEngine()
        assert engine.method == ConsensusMethod.WEIGHTED
        assert engine.min_votes == 1

    def test_create_with_method(self):
        engine = ConsensusEngine(method=ConsensusMethod.MAJORITY)
        assert engine.method == ConsensusMethod.MAJORITY

    def test_resolve_empty_list(self):
        engine = ConsensusEngine()
        winner, confidence, meta = engine.resolve([])
        assert winner == VoteType.ABSTAIN
        assert confidence == 0.0

    def test_majority_simple(self):
        engine = ConsensusEngine(method=ConsensusMethod.MAJORITY)
        opinions = [
            AgentOpinion(agent_name="A", agent_role="R1", vote=VoteType.AGREE, confidence=0.8),
            AgentOpinion(agent_name="B", agent_role="R2", vote=VoteType.AGREE, confidence=0.7),
            AgentOpinion(agent_name="C", agent_role="R3", vote=VoteType.DISAGREE, confidence=0.6),
        ]
        winner, confidence, meta = engine.resolve(opinions)
        assert winner == VoteType.AGREE
        assert 0 < confidence <= 1.0
        assert meta["method"] == "majority"

    def test_weighted_respects_confidence(self):
        engine = ConsensusEngine(method=ConsensusMethod.WEIGHTED)
        opinions = [
            AgentOpinion(agent_name="High", agent_role="R1", vote=VoteType.STRONGLY_AGREE, confidence=0.9),
            AgentOpinion(agent_name="Low", agent_role="R2", vote=VoteType.DISAGREE, confidence=0.1),
        ]
        winner, confidence, meta = engine.resolve(opinions)
        assert winner == VoteType.STRONGLY_AGREE
        assert confidence > 0.5

    def test_borda_count(self):
        engine = ConsensusEngine(method=ConsensusMethod.BORDA)
        opinions = [
            AgentOpinion(agent_name="A", agent_role="R1", vote=VoteType.STRONGLY_AGREE, confidence=1.0),
            AgentOpinion(agent_name="B", agent_role="R2", vote=VoteType.AGREE, confidence=1.0),
            AgentOpinion(agent_name="C", agent_role="R3", vote=VoteType.DISAGREE, confidence=1.0),
        ]
        winner, confidence, meta = engine.resolve(opinions)
        assert winner in (VoteType.STRONGLY_AGREE, VoteType.AGREE)
        assert "borda_points" in meta

    def test_supermajority_majority_wins(self):
        """2 of 3 agree (66.7%) - meets 2/3 supermajority."""
        engine = ConsensusEngine(
            method=ConsensusMethod.SUPERMAJORITY,
            supermajority_threshold=0.66,
        )
        opinions = [
            AgentOpinion(agent_name="A", agent_role="R1", vote=VoteType.AGREE, confidence=1.0),
            AgentOpinion(agent_name="B", agent_role="R2", vote=VoteType.AGREE, confidence=1.0),
            AgentOpinion(agent_name="C", agent_role="R3", vote=VoteType.DISAGREE, confidence=1.0),
        ]
        winner, confidence, meta = engine.resolve(opinions)
        assert winner == VoteType.AGREE
        assert meta["achieved_ratio"] >= 0.66

    def test_supermajority_not_reached(self):
        """50% < 66.7%, should abstain."""
        engine = ConsensusEngine(
            method=ConsensusMethod.SUPERMAJORITY,
            supermajority_threshold=0.667,
        )
        opinions = [
            AgentOpinion(agent_name="A", agent_role="R1", vote=VoteType.AGREE, confidence=1.0),
            AgentOpinion(agent_name="B", agent_role="R2", vote=VoteType.DISAGREE, confidence=1.0),
        ]
        winner, confidence, meta = engine.resolve(opinions)
        assert winner == VoteType.ABSTAIN
        assert meta["achieved_ratio"] == 0.5

    def test_all_strongly_disagree(self):
        engine = ConsensusEngine(method=ConsensusMethod.MAJORITY)
        opinions = [
            AgentOpinion(agent_name="A", agent_role="R1", vote=VoteType.STRONGLY_DISAGREE, confidence=0.9),
            AgentOpinion(agent_name="B", agent_role="R2", vote=VoteType.STRONGLY_DISAGREE, confidence=0.8),
        ]
        winner, confidence, _ = engine.resolve(opinions)
        assert winner == VoteType.STRONGLY_DISAGREE

    def test_mixed_with_abstain(self):
        engine = ConsensusEngine(method=ConsensusMethod.MAJORITY)
        opinions = [
            AgentOpinion(agent_name="A", agent_role="R1", vote=VoteType.AGREE, confidence=0.5),
            AgentOpinion(agent_name="B", agent_role="R2", vote=VoteType.ABSTAIN, confidence=0.0),
            AgentOpinion(agent_name="C", agent_role="R3", vote=VoteType.AGREE, confidence=0.6),
        ]
        winner, confidence, _ = engine.resolve(opinions)
        assert winner == VoteType.AGREE

    def test_repr(self):
        engine = ConsensusEngine(method=ConsensusMethod.BORDA)
        rep = repr(engine)
        assert "borda" in rep.lower()


class TestConsensusMethod:
    """Test ConsensusMethod enum."""

    def test_method_values(self):
        assert ConsensusMethod.MAJORITY.value == "majority"
        assert ConsensusMethod.WEIGHTED.value == "weighted"
        assert ConsensusMethod.BORDA.value == "borda"
        assert ConsensusMethod.SUPERMAJORITY.value == "supermajority"


class TestConsensusResultProperties:
    """Test ConsensusResult edge cases."""

    def test_no_agents(self):
        result = ConsensusResult(topic="Test", consensus_answer="", total_agents=0)
        assert result.agreement_percentage == 0.0
        assert result.total_agents == 0

    def test_full_agreement(self):
        result = ConsensusResult(
            topic="Test", consensus_answer="All agree",
            confidence=1.0, total_agents=5, agreement_percentage=1.0,
        )
        assert result.confidence == 1.0
        assert result.agreement_percentage == 1.0
