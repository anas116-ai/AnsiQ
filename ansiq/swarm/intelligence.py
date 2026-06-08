"""Swarm Intelligence — agents collaborate like a hive mind.

Instead of a single agent making decisions, a swarm of agents:
1. Each forms their own opinion on a task
2. Votes or debates to reach consensus
3. Produces a final answer that leverages collective intelligence

This goes beyond CrewAI's sequential/council models by adding
true multi-agent collaboration with weighted voting.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from ansiq.core.agent import Agent

logger = logging.getLogger(__name__)


class VoteType(StrEnum):
    """Type of vote an agent can cast."""

    AGREE = "agree"
    DISAGREE = "disagree"
    ABSTAIN = "abstain"
    STRONGLY_AGREE = "strongly_agree"
    STRONGLY_DISAGREE = "strongly_disagree"


class AgentOpinion(BaseModel):
    """An individual agent's opinion on a matter."""

    agent_name: str
    agent_role: str
    vote: VoteType
    reasoning: str = ""
    confidence: float = 0.5
    """How confident the agent is (0.0 to 1.0)."""

    suggestions: str = ""
    """Alternative suggestions or improvements."""


class ConsensusResult(BaseModel):
    """Result of a swarm consensus process."""

    topic: str
    consensus_answer: str
    confidence: float = 0.0
    """Overall consensus confidence (0.0 to 1.0)."""

    votes: list[AgentOpinion] = Field(default_factory=list)
    vote_summary: dict[str, int] = Field(default_factory=dict)
    total_agents: int = 0
    agreement_percentage: float = 0.0
    execution_time: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SwarmConfig(BaseModel):
    """Configuration for swarm intelligence."""

    rounds: int = 1
    """Number of discussion rounds before final consensus."""

    require_unanimous: bool = False
    """If True, all agents must agree."""

    min_agreement: float = 0.6
    """Minimum agreement ratio (0.0 to 1.0) to reach consensus."""

    weight_by_confidence: bool = True
    """Weight votes by agent confidence."""

    allow_debate: bool = False
    """If True, agents can debate before voting."""

    debate_rounds: int = 2
    """Number of debate rounds before final vote."""

    timeout_per_agent: float = 30.0
    """Maximum time for each agent to respond."""


class SwarmIntelligence:
    """Swarm intelligence orchestrator.

    Coordinates multiple agents to reach consensus through
    voting, weighted decision-making, and optional debate.

    Usage:
        swarm = SwarmIntelligence(
            agents=[researcher, analyst, critic],
            config=SwarmConfig(rounds=2)
        )

        result = await swarm.reach_consensus(
            "What is the best cloud provider for ML?"
        )
        print(f"Consensus: {result.consensus_answer}")
        print(f"Confidence: {result.confidence}")
    """

    def __init__(
        self,
        agents: list[Agent],
        config: SwarmConfig | None = None,
    ):
        if not agents:
            raise ValueError("At least one agent is required")

        self.agents = agents
        self.config = config or SwarmConfig()

    async def reach_consensus(
        self,
        topic: str,
        context: str | None = None,
    ) -> ConsensusResult:
        """Orchestrate agents to reach consensus on a topic.

        Process:
        1. Each agent forms initial opinion
        2. If debate enabled, agents debate
        3. Agents vote
        4. Consensus is calculated with weighted voting
        5. If no consensus, repeat rounds
        """
        start_time = time.time()
        logger.info(
            "Swarm consensus on '%s' with %d agents, %d rounds",
            topic[:50],
            len(self.agents),
            self.config.rounds,
        )

        all_opinions: list[AgentOpinion] = []

        for round_num in range(1, self.config.rounds + 1):
            logger.info("Consensus round %d/%d", round_num, self.config.rounds)

            # Step 1: Each agent forms opinion
            round_opinions = await self._gather_opinions(topic, context)
            all_opinions.extend(round_opinions)

            # Step 2: Optional debate
            if self.config.allow_debate and round_num < self.config.rounds:
                await self._conduct_debate(topic, round_opinions, context)

            # Step 3: Check for early consensus
            if round_num < self.config.rounds:
                early_result = self._calculate_consensus(topic, all_opinions)
                if early_result.agreement_percentage >= self.config.min_agreement:
                    if self.config.require_unanimous:
                        if early_result.agreement_percentage >= 1.0:
                            early_result.execution_time = time.time() - start_time
                            return early_result
                    else:
                        early_result.execution_time = time.time() - start_time
                        return early_result

        # Final consensus calculation
        result = self._calculate_consensus(topic, all_opinions)
        result.execution_time = time.time() - start_time
        return result

    async def _gather_opinions(
        self,
        topic: str,
        context: str | None = None,
    ) -> list[AgentOpinion]:
        """Gather opinions from all agents in parallel."""
        opinions: list[AgentOpinion] = []

        async def get_agent_opinion(agent: Agent) -> AgentOpinion:
            """Get a single agent's opinion."""
            # Safely extract agent identity fields, with fallbacks
            agent_name = getattr(agent.identity, "name", None) or getattr(
                agent.identity, "role", "agent"
            )
            agent_role = getattr(agent.identity, "role", "agent")
            agent_goal = getattr(agent.identity, "goal", "achieve the best outcome")

            prompt = (
                f"Topic: {topic}\n\n"
                f"You are {agent_role}. Your goal is {agent_goal}.\n\n"
                f"Please analyze this topic and provide:\n"
                f"1. Your position: AGREE, DISAGREE, STRONGLY_AGREE, STRONGLY_DISAGREE, or ABSTAIN\n"
                f"2. Your reasoning (2-3 sentences)\n"
                f"3. Your confidence level (0.0 to 1.0)\n"
                f"4. Any suggestions or alternatives\n\n"
                f"Format your response as:\n"
                f"VOTE: <your vote>\n"
                f"REASONING: <your reasoning>\n"
                f"CONFIDENCE: <0.0-1.0>\n"
                f"SUGGESTIONS: <optional suggestions>"
            )

            try:
                response = await agent.run(task=prompt, context=context)
                content = response.content if hasattr(response, "content") else str(response)

                # Parse structured response
                vote = VoteType.ABSTAIN
                reasoning = content
                confidence = 0.5
                suggestions = ""

                for line in content.split("\n"):
                    line_lower = line.lower().strip()
                    if line_lower.startswith("vote:"):
                        vote_text = line.split(":", 1)[1].strip().lower()
                        if "strongly agree" in vote_text:
                            vote = VoteType.STRONGLY_AGREE
                        elif "strongly disagree" in vote_text:
                            vote = VoteType.STRONGLY_DISAGREE
                        elif "agree" in vote_text:
                            vote = VoteType.AGREE
                        elif "disagree" in vote_text:
                            vote = VoteType.DISAGREE
                        elif "abstain" in vote_text:
                            vote = VoteType.ABSTAIN
                    elif line_lower.startswith("confidence:"):
                        try:
                            confidence = float(line.split(":", 1)[1].strip())
                        except ValueError:
                            confidence = 0.5
                    elif line_lower.startswith("suggestions:"):
                        suggestions = line.split(":", 1)[1].strip()
                    elif line_lower.startswith("reasoning:"):
                        reasoning = line.split(":", 1)[1].strip()

                return AgentOpinion(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    vote=vote,
                    reasoning=reasoning,
                    confidence=min(max(confidence, 0.0), 1.0),
                    suggestions=suggestions,
                )

            except Exception as e:
                logger.warning("Agent '%s' failed to form opinion: %s", agent_name, e)
                return AgentOpinion(
                    agent_name=agent_name,
                    agent_role=agent_role,
                    vote=VoteType.ABSTAIN,
                    reasoning=f"Failed to form opinion: {e}",
                    confidence=0.0,
                )

        # Gather all opinions in parallel
        tasks = [get_agent_opinion(agent) for agent in self.agents]
        # Compute a safe timeout — fall back to default if max_tokens is 0 or unset
        try:
            max_tokens = max((getattr(a.config, "max_tokens", 0) or 0) for a in self.agents)
        except (ValueError, TypeError):
            max_tokens = 0
        timeout_secs = (max_tokens / 10 if max_tokens > 0 else 60) + 60

        try:
            opinions = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout_secs,
            )
            # Filter out exceptions
            opinions = [o for o in opinions if isinstance(o, AgentOpinion)]
        except TimeoutError:
            logger.warning("Swarm opinion gathering timed out")
            opinions = []

        return opinions

    async def _conduct_debate(
        self,
        topic: str,
        opinions: list[AgentOpinion],
        context: str | None = None,
    ) -> None:
        """Conduct a debate round where agents respond to each other."""
        if not opinions:
            return

        # Summarize current opinions for debate
        opinion_summary = "\n".join(
            f"- {o.agent_name} ({o.agent_role}): {o.vote.value} "
            f"(confidence: {o.confidence:.2f})"
            f"\n  Reasoning: {o.reasoning[:200]}"
            for o in opinions
        )

        debate_prompt = (
            f"Topic: {topic}\n\n"
            f"Current opinions from your fellow agents:\n"
            f"{opinion_summary}\n\n"
            f"Review the opinions above. Do you want to:\n"
            f"1. Change your vote based on strong arguments?\n"
            f"2. Strengthen your position with counter-arguments?\n"
            f"3. Suggest a compromise or alternative?\n\n"
            f"Your debate response:"
        )

        logger.info("Conducting debate round...")

        # All agents respond to debate in parallel
        async def debate_response(agent: Agent) -> None:
            try:
                await agent.run(task=debate_prompt, context=context)
            except Exception as e:
                logger.debug("Agent '%s' debate response failed: %s", agent.identity.role, e)

        await asyncio.gather(
            *[debate_response(a) for a in self.agents],
            return_exceptions=True,
        )

    def _calculate_consensus(
        self,
        topic: str,
        opinions: list[AgentOpinion],
    ) -> ConsensusResult:
        """Calculate consensus from all opinions using weighted voting."""
        if not opinions:
            return ConsensusResult(
                topic=topic,
                consensus_answer="No opinions gathered",
                confidence=0.0,
                total_agents=len(self.agents),
            )

        # Count votes
        vote_counts: dict[str, int] = {}
        weighted_agree = 0.0
        weighted_total = 0.0
        latest_opinions: dict[str, AgentOpinion] = {}

        # Use latest opinion from each agent (for multi-round)
        for opinion in reversed(opinions):
            if opinion.agent_name not in latest_opinions:
                latest_opinions[opinion.agent_name] = opinion

        for opinion in latest_opinions.values():
            vote_counts[opinion.vote.value] = vote_counts.get(opinion.vote.value, 0) + 1

            weight = opinion.confidence if self.config.weight_by_confidence else 1.0
            weighted_total += weight

            if opinion.vote in (VoteType.AGREE, VoteType.STRONGLY_AGREE):
                weighted_agree += weight * (1.0 if opinion.vote == VoteType.AGREE else 1.5)

        # Calculate consensus
        total_votes = len(latest_opinions)
        agrees = vote_counts.get("agree", 0) + vote_counts.get("strongly_agree", 0)
        agreement_percentage = agrees / max(total_votes, 1)

        # Confidence based on weighted voting
        if weighted_total > 0:
            confidence = weighted_agree / weighted_total
        else:
            confidence = agreement_percentage

        confidence = min(max(confidence, 0.0), 1.0)

        # Generate consensus answer
        if agreement_percentage >= self.config.min_agreement:
            # Majority reached
            agreeing_opinions = [
                o
                for o in latest_opinions.values()
                if o.vote in (VoteType.AGREE, VoteType.STRONGLY_AGREE)
            ]

            if agreeing_opinions:
                consensus_answer = f"Consensus reached ({agreement_percentage:.0%} agreement):\n"
                reasoning_parts = []
                for o in agreeing_opinions[:3]:
                    reasoning_parts.append(f"- {o.agent_name}: {o.reasoning[:150]}")
                consensus_answer += "\n".join(reasoning_parts)
            else:
                consensus_answer = "No clear consensus position identified."
        else:
            # No majority
            disagreeing = [
                o
                for o in latest_opinions.values()
                if o.vote in (VoteType.DISAGREE, VoteType.STRONGLY_DISAGREE)
            ]

            if len(disagreeing) >= total_votes / 2:
                consensus_answer = (
                    f"Majority disagreement ({agreement_percentage:.0%} agreement). "
                    "Further analysis needed."
                )
            else:
                consensus_answer = (
                    f"No consensus reached ({agreement_percentage:.0%} agreement). "
                    f"Additional discussion required."
                )

        # Add suggestions if any
        suggestions = [o.suggestions for o in latest_opinions.values() if o.suggestions]
        if suggestions:
            consensus_answer += "\n\nSuggestions:\n" + "\n".join(
                f"- {s[:200]}" for s in suggestions[:3]
            )

        return ConsensusResult(
            topic=topic,
            consensus_answer=consensus_answer,
            confidence=round(confidence, 4),
            votes=list(latest_opinions.values()),
            vote_summary=vote_counts,
            total_agents=total_votes,
            agreement_percentage=round(agreement_percentage, 4),
            metadata={
                "total_opinions_collected": len(opinions),
                "weighted_by_confidence": self.config.weight_by_confidence,
            },
        )

    async def vote(
        self,
        topic: str,
        options: list[str],
        context: str | None = None,
    ) -> ConsensusResult:
        """Have agents vote on multiple choice options.

        Usage:
            result = await swarm.vote(
                "Best programming language for AI?",
                options=["Python", "Rust", "Julia"]
            )
        """
        options_text = "\n".join(f"{i + 1}. {opt}" for i, opt in enumerate(options))
        prompt = (
            f"Vote on the following options:\n\n"
            f"Question: {topic}\n\n"
            f"Options:\n{options_text}\n\n"
            f"Choose the best option and provide your reasoning."
        )

        return await self.reach_consensus(prompt, context)

    def __repr__(self) -> str:
        return (
            f"SwarmIntelligence(agents={len(self.agents)}, "
            f"rounds={self.config.rounds}, "
            f"debate={self.config.allow_debate})"
        )
