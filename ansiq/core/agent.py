"""Agent — the fundamental worker unit with brain, hooks, memory, tools, and LLM.

Now integrates:
- Brain/ReasoningEngine: structured thinking before actions
- AgentHooks: pre/post execution lifecycle hooks
- CompositeMemoryProvider: multi-provider memory
- Trajectory recording: for self-improvement
- Knowledge/RAG: from crew-level knowledge sources
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from ansiq.llm.base import ImageBlock, LLMMessage, LLMProvider, LLMResponse, ProviderFactory

logger = logging.getLogger(__name__)


class AgentIdentity(BaseModel):
    """Who the agent is — its role, purpose, and background."""

    role: str = Field(description="The agent's role (e.g., 'Senior Researcher')")
    goal: str = Field(description="What the agent is trying to achieve")
    backstory: str = Field(description="The agent's background and personality")


class AgentConfig(BaseModel):
    """Configuration for an agent."""

    identity: AgentIdentity
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    temperature: float = 0.7
    max_tokens: int = 4096
    allow_delegation: bool = False
    verbose: bool = False
    max_retries: int = 3
    thinking_mode: str = "standard"
    """Thinking protocol mode: minimal, standard, or deep."""


class Agent:
    """An AI agent with brain, hooks, memory, tools, and LLM capabilities.

    Enhanced features:
    - Brain: structured reasoning/thinking before each task
    - Hooks: pre/post task lifecycle hooks
    - Memory: multi-provider composite memory (FTS5 + Entity + Semantic)
    - Trajectories: records execution paths for self-improvement
    - Knowledge: RAG context from attached knowledge sources
    """

    def __init__(
        self,
        identity: AgentIdentity | dict[str, str],
        provider: LLMProvider | None = None,
        config: AgentConfig | dict[str, Any] | None = None,
        tools: list[Any] | None = None,
        memory: Any | None = None,
        skills: list[Any] | None = None,
        knowledge: Any | None = None,
        hooks: Any | None = None,
        brain: Any | None = None,
        trajectory_recorder: Any | None = None,
    ):
        if isinstance(identity, dict):
            identity = AgentIdentity(**identity)

        self.identity = identity

        if isinstance(config, dict):
            config = AgentConfig(identity=self.identity, **config)
        self.config = config or AgentConfig(identity=identity)
        self.tools = tools or []
        self.memory = memory
        self.skills = skills or []
        self.knowledge = knowledge
        self.config.identity = identity

        if provider is None:
            self._init_provider()
        else:
            self._provider = provider

        self._conversation_history: list[LLMMessage] = []

        # Brain — reasoning engine
        if brain is not None:
            self._brain = brain
        else:
            from ansiq.brain.reasoning import ReasoningEngine, ThinkingProtocol

            self._brain = ReasoningEngine(
                protocol=ThinkingProtocol(self.config.thinking_mode),
                agent_role=self.identity.role,
            )

        # Hooks — lifecycle hooks
        if hooks is not None:
            self._hooks = hooks
        else:
            from ansiq.core.hooks import AgentHooks

            self._hooks = AgentHooks()

        # Trajectory recorder
        self._trajectory_recorder = trajectory_recorder

    @property
    def brain(self) -> Any:
        """Get the agent's reasoning engine."""
        return self._brain

    @property
    def hooks(self) -> Any:
        """Get the agent's hook system."""
        return self._hooks

    def _init_provider(self) -> None:
        """Initialize the LLM provider based on config."""
        try:
            if self.config.llm_provider.lower() == "ollama":
                self._provider = ProviderFactory.create(
                    "ollama",
                    model=self.config.llm_model,
                    base_url=self.config.llm_base_url,
                    temperature=self.config.temperature,
                )
            else:
                self._provider = ProviderFactory.create(
                    self.config.llm_provider,
                    model=self.config.llm_model,
                    api_key=self.config.llm_api_key,
                    base_url=self.config.llm_base_url,
                    temperature=self.config.temperature,
                )
        except Exception as e:
            logger.warning(
                "Failed to initialize provider '%s': %s. Falling back to Ollama.",
                self.config.llm_provider,
                e,
            )
            self._provider = ProviderFactory.create(
                "ollama",
                model="llama3.2",
                temperature=self.config.temperature,
            )

    @property
    def provider(self) -> LLMProvider:
        return self._provider

    @provider.setter
    def provider(self, new_provider: LLMProvider) -> None:
        self._provider = new_provider

    def _build_system_prompt(
        self,
        task_context: str | None = None,
    ) -> str:
        """Build the system prompt including identity, tools, memory, skills, and knowledge."""
        parts = [
            f"You are {self.identity.role}.",
            f"Your goal: {self.identity.goal}",
            f"Your background: {self.identity.backstory}",
            "",
        ]

        if self.config.thinking_mode != "minimal":
            parts.append(
                "Before each action, think step by step. Use the following thinking structure:"
            )
            parts.append("  1. Analyze: understand what needs to be done")
            parts.append("  2. Plan: create a clear plan of action")
            parts.append("  3. Execute: carry out the plan")
            parts.append("  4. Evaluate: check the result")
            parts.append("")

        # Tools
        if self.tools:
            parts.append("You have access to the following tools:")
            for tool in self.tools:
                parts.append(f"- {tool.get_name()}: {tool.get_description()}")
            parts.append("")

        # Memory context
        if self.memory:
            try:
                memories = self.memory.get_relevant_context()
                if memories:
                    parts.append("Relevant context from memory:")
                    parts.append(memories)
                    parts.append("")
            except Exception:
                pass

        # Knowledge context (RAG)
        if self.knowledge and task_context:
            try:
                context = self.knowledge.get_context(task_context)
                if context:
                    parts.append("Relevant knowledge:")
                    parts.append(context)
                    parts.append("")
            except Exception:
                pass

        # Skills
        if self.skills:
            parts.append("Available skills:")
            for skill in self.skills:
                parts.append(f"- {skill.get_name()}: {skill.get_description()}")
            parts.append("")

        return "\n".join(parts)

    def add_tool(self, tool: Any) -> None:
        """Add a tool to the agent's toolkit."""
        self.tools.append(tool)

    def add_skill(self, skill: Any) -> None:
        """Add a skill to the agent's repertoire."""
        self.skills.append(skill)

    async def _prepare_messages(self, task: str, context: str | None = None) -> list[LLMMessage]:
        """Build the full message list for a task.

        Shared by both sync chat and streaming paths.
        """
        messages = [LLMMessage.system(self._build_system_prompt(task_context=task or context))]

        if context:
            messages.append(LLMMessage.system(f"Additional context:\n{context}"))

        # Add relevant memory context
        if self.memory:
            try:
                from ansiq.memory.providers import CompositeMemoryProvider

                if isinstance(self.memory, CompositeMemoryProvider):
                    memory_ctx = self.memory.get_relevant_context(task)
                else:
                    if hasattr(self.memory, "search"):
                        memories = self.memory.search(task)
                        memory_ctx = str(memories) if memories else ""
                    else:
                        memory_ctx = ""
                if memory_ctx:
                    messages.append(LLMMessage.system(f"Memory context:\n{memory_ctx}"))
            except Exception:
                pass

        # Add conversation history
        messages.extend(self._conversation_history[-10:])

        return messages

    async def _finish_run(self, task: str, content: str, success: bool = True) -> None:
        """Post-execution bookkeeping — shared by sync and streaming paths.

        Saves conversation history, memory, trajectory, and fires hooks.
        """
        from ansiq.core.hooks import HookEvent

        self._conversation_history.append(LLMMessage.user(task))
        self._conversation_history.append(LLMMessage.assistant(content))

        # Store in memory
        if self.memory:
            try:
                self.memory.store(
                    content,
                    agent_id=self.identity.role,
                    tags=["conversation"],
                    metadata={"task": task},
                )
            except Exception:
                pass

        # Record trajectory
        if self._trajectory_recorder and success:
            try:
                from ansiq.learning.trajectory import Trajectory

                traj = Trajectory(
                    task_description=task,
                    agent_role=self.identity.role,
                    overall_success=True,
                )
                traj.add_step(
                    action="execute_task",
                    reasoning=self._brain.get_thought_summary(),
                    output_data=content[:500],
                    success=True,
                )
                traj.complete(success=True)
                self._trajectory_recorder.save(traj)
            except Exception:
                pass

        # Reflect on result
        await self._brain.reflect_on_result(task, content, success=success)

        # Fire AFTER_TASK hook
        await self._hooks.execute(
            HookEvent.AFTER_TASK,
            task=task,
            result=content,
            agent=self,
        )

    async def run(
        self,
        task: str,
        context: str | None = None,
        stream: bool = False,
        images: list[ImageBlock] | None = None,
    ) -> LLMResponse | AsyncIterator[str]:
        """Execute a task with thinking, hooks, and memory.

        Args:
            task: The task description to execute.
            context: Optional additional context.
            stream: If True, returns an async iterator yielding tokens.
                    If False, returns the full LLMResponse.
            images: Optional list of images to include with the task.

        Returns:
            LLMResponse when stream=False.
            AsyncIterator[str] when stream=True.
        """
        from ansiq.core.hooks import HookEvent

        # Fire BEFORE_TASK hook
        hook_result = await self._hooks.execute(
            HookEvent.BEFORE_TASK,
            task=task,
            agent=self,
        )

        # Check if hook aborted
        for r in hook_result:
            if r.abort:
                return LLMResponse(content="Task aborted by hook", model="")

        # Start brain thinking
        await self._brain.analyze_task(task, context)

        # Build messages
        messages = await self._prepare_messages(task, context)

        # Add the current task (with optional images)
        messages.append(LLMMessage.user(task, images=images or []))

        if stream:
            return self._run_streaming(task, messages)
        else:
            response = await self._provider.chat(messages)
            await self._finish_run(task, response.content, success=True)
            return response

    async def _run_streaming(self, task: str, messages: list[LLMMessage]) -> AsyncIterator[str]:
        """Internal streaming implementation.

        Yields tokens as they arrive from the LLM provider.
        After streaming completes, saves conversation history,
        memory, trajectory, and fires hooks.
        """
        accumulated = ""
        try:
            async for token in self._provider.stream_chat(messages):
                accumulated += token
                yield token
        finally:
            # Post-execution bookkeeping (runs even if streaming was interrupted)
            if accumulated.strip():
                await self._finish_run(task, accumulated, success=True)
            else:
                await self._finish_run(task, accumulated, success=False)

    async def chat(
        self,
        message: str,
        context: str | None = None,
        stream: bool = False,
        images: list[ImageBlock] | None = None,
    ) -> LLMResponse | AsyncIterator[str]:
        """Have a conversation with the agent.

        Args:
            message: The user's message.
            context: Optional additional context.
            stream: If True, returns an async iterator yielding tokens.
            images: Optional list of images to include with the message.

        Returns:
            LLMResponse when stream=False.
            AsyncIterator[str] when stream=True.
        """
        return await self.run(message, context=context, stream=stream, images=images)

    def reset_conversation(self) -> None:
        """Clear conversation history."""
        self._conversation_history.clear()
        if hasattr(self, "_brain") and self._brain:
            self._brain.reset()

    def __repr__(self) -> str:
        return f"Agent(role='{self.identity.role}', model='{self.config.llm_model}')"
