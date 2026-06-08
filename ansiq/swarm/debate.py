"""Debate Engine — structured multi-agent debates for deeper reasoning.

Multiple agents argue different sides of a question, refining
their positions through successive rounds. The debate process:
1. Opening statements from each agent
2. Rebuttal rounds
3. Closing arguments
4. Final consensus
"""

from __future__ import annotations

import asyncio
import logging
import time

from pydantic import BaseModel, Field

from ansiq.core.agent import Agent
from ansiq.swarm.intelligence import ConsensusResult, SwarmConfig, VoteType

logger = logging.getLogger(__name__)


class DebateRound(BaseModel):
    """A single round in a debate."""

    round_number: int
    name: str
    statements: dict[str, str] = Field(default_factory=dict)
    """Agent name -> their statement in this round."""


class DebateResult(BaseModel):
    """Result of a complete debate."""

    topic: str
    rounds: list[DebateRound] = Field(default_factory=list)
    winner: str | None = None
    """The agent who persuaded the most."""

    consensus: ConsensusResult | None = None
    """Final consensus after debate."""

    execution_time: float = 0.0
    total_rounds: int = 0
    agent_participants: list[str] = Field(default_factory=list)


class DebateEngine:
    """Structured debate orchestrator.

    Facilitates multi-round debates where agents argue their
    positions and respond to counter-arguments.

    Usage:
        debate = DebateEngine(
            agents=[proponent, opponent, judge],
            config=SwarmConfig(debate_rounds=3)
        )

        result = await debate.conduct(
            "Should AI development be regulated?"
        )
        print(f"Winner: {result.winner}")
    """

    def __init__(
        self,
        agents: list[Agent],
        config: SwarmConfig | None = None,
    ):
        if len(agents) < 2:
            raise ValueError("Debate requires at least 2 agents")

        self.agents = agents
        self.config = config or SwarmConfig(debate_rounds=2, allow_debate=True)

    async def conduct(
        self,
        topic: str,
        context: str | None = None,
        assign_positions: list[str] | None = None,
    ) -> DebateResult:
        """Conduct a full debate with multiple rounds.

        Args:
            topic: The question or topic to debate
            context: Optional background context
            assign_positions: Optional list of positions to assign to agents
                (e.g., ["FOR", "AGAINST", "JUDGE"])
                If not provided, agents choose their own positions.

        Returns:
            DebateResult with all rounds and final consensus
        """
        start_time = time.time()
        total_rounds = self.config.debate_rounds + 1  # +1 for opening

        logger.info(
            "Debate started: '%s' with %d agents, %d rounds",
            topic[:60],
            len(self.agents),
            total_rounds,
        )

        result = DebateResult(
            topic=topic,
            agent_participants=[a.identity.role for a in self.agents],
            total_rounds=total_rounds,
        )

        debate_history: list[str] = []

        # Round 1: Opening statements
        opening_round = DebateRound(round_number=1, name="Opening Statements")

        opening_tasks = []
        for i, agent in enumerate(self.agents):
            position = assign_positions[i] if assign_positions and i < len(assign_positions) else ""
            task = self._get_opening(agent, topic, position, context)
            opening_tasks.append(task)

        opening_results = await asyncio.gather(*opening_tasks, return_exceptions=True)

        for i, agent in enumerate(self.agents):
            statement = (
                opening_results[i]
                if isinstance(opening_results[i], str)
                else str(opening_results[i])
            )
            opening_round.statements[agent.identity.role] = statement
            debate_history.append(f"[{agent.identity.role}] {statement[:200]}")

        result.rounds.append(opening_round)

        # Rounds 2-N: Rebuttals
        for round_num in range(2, total_rounds + 1):
            round_name = "Rebuttal" if round_num < total_rounds else "Closing Arguments"
            debate_round = DebateRound(round_number=round_num, name=round_name)

            history_text = "\n".join(debate_history[-len(self.agents) * 2 :])

            rebuttal_tasks = []
            for agent in self.agents:
                task = self._get_rebuttal(
                    agent, topic, history_text, round_num, total_rounds, context
                )
                rebuttal_tasks.append(task)

            rebuttal_results = await asyncio.gather(*rebuttal_tasks, return_exceptions=True)

            for i, agent in enumerate(self.agents):
                statement = (
                    rebuttal_results[i]
                    if isinstance(rebuttal_results[i], str)
                    else str(rebuttal_results[i])
                )
                debate_round.statements[agent.identity.role] = statement
                debate_history.append(f"[{agent.identity.role}] {statement[:200]}")

            result.rounds.append(debate_round)

        # Final: Consensus vote
        consensus = await self._reach_consensus(topic, debate_history, context)
        result.consensus = consensus

        # Determine winner
        if consensus and consensus.votes:
            # Winner is the agent whose position has most agreement
            winning_agent = max(
                consensus.votes,
                key=lambda v: (
                    v.confidence if v.vote in (VoteType.AGREE, VoteType.STRONGLY_AGREE) else 0
                ),
            )
            result.winner = winning_agent.agent_name if winning_agent.confidence > 0.5 else None

        result.execution_time = time.time() - start_time
        logger.info(
            "Debate complete: '%s' - %d rounds, %.2fs",
            topic[:40],
            total_rounds,
            result.execution_time,
        )

        return result

    async def _get_opening(
        self,
        agent: Agent,
        topic: str,
        position: str,
        context: str | None = None,
    ) -> str:
        """Get an agent's opening statement."""
        position_text = (
            f"\nYou have been assigned the position: {position}"
            if position
            else "\nTake whatever position you believe is correct."
        )

        prompt = (
            f"Debate Topic: {topic}\n\n"
            f"You are {agent.identity.role}. {agent.identity.goal}{position_text}\n\n"
            f"Provide your OPENING STATEMENT for this debate.\n"
            f"State your position clearly and provide your strongest arguments.\n"
            f"Be persuasive and concise (2-3 paragraphs).\n\n"
            f"Your opening statement:"
        )

        try:
            response = await agent.run(task=prompt, context=context)
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.warning("Agent '%s' opening statement failed: %s", agent.identity.role, e)
            return f"Unable to provide opening statement. ({e})"

    async def _get_rebuttal(
        self,
        agent: Agent,
        topic: str,
        history: str,
        round_num: int,
        total_rounds: int,
        context: str | None = None,
    ) -> str:
        """Get an agent's rebuttal or closing argument."""
        is_closing = round_num == total_rounds

        if is_closing:
            prompt = (
                f"Debate Topic: {topic}\n\n"
                f"You are {agent.identity.role}.\n\n"
                f"Debate history so far:\n{history}\n\n"
                f"This is your CLOSING ARGUMENT.\n"
                f"Summarize your position, address counter-arguments, "
                f"and make your final persuasive case.\n\n"
                f"Your closing argument:"
            )
        else:
            prompt = (
                f"Debate Topic: {topic}\n\n"
                f"You are {agent.identity.role}.\n\n"
                f"Debate history so far:\n{history}\n\n"
                f"This is REBUTTAL round {round_num - 1}.\n"
                f"Respond to the arguments made by others.\n"
                f"Point out flaws in their reasoning and strengthen your position.\n\n"
                f"Your rebuttal:"
            )

        try:
            response = await agent.run(task=prompt, context=context)
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            logger.warning("Agent '%s' rebuttal failed: %s", agent.identity.role, e)
            return f"Unable to provide rebuttal. ({e})"

    async def _reach_consensus(
        self,
        topic: str,
        debate_history: list[str],
        context: str | None = None,
    ) -> ConsensusResult | None:
        """Reach consensus after debate."""
        try:
            from ansiq.swarm.intelligence import SwarmIntelligence

            swarm = SwarmIntelligence(
                agents=self.agents,
                config=self.config,
            )

            consensus_topic = (
                f"After debating: {topic}\n\n"
                f"Debate summary:\n"
                + "\n".join(debate_history[-8:])
                + "\n\nBased on this debate, what is the best conclusion?"
            )

            result = await swarm.reach_consensus(consensus_topic, context)
            return result
        except Exception as e:
            logger.warning("Post-debate consensus failed: %s", e)
            return None

    def __repr__(self) -> str:
        return f"DebateEngine(agents={len(self.agents)}, rounds={self.config.debate_rounds})"
