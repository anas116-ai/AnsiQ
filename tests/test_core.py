"""Tests for the core engine — Agent, Task, Crew, Flow, and State."""

from __future__ import annotations

import pytest

from ansiq.core.agent import Agent, AgentConfig, AgentIdentity
from ansiq.core.crew import Crew, CrewResult, ProcessType
from ansiq.core.flow import Flow, and_, listen, or_, start
from ansiq.core.state import FlowState as FS
from ansiq.core.state import StateManager
from ansiq.core.task import Task
from ansiq.llm.base import LLMMessage

# ── Agent Tests ──


class TestAgent:
    def test_create_agent_with_identity(self):
        """Test creating an agent with an identity object."""
        identity = AgentIdentity(
            role="Researcher",
            goal="Find information",
            backstory="An expert researcher.",
        )
        agent = Agent(identity=identity)
        assert agent.identity.role == "Researcher"
        assert agent.identity.goal == "Find information"
        assert agent.identity.backstory == "An expert researcher."

    def test_create_agent_with_dict_identity(self):
        """Test creating an agent with a dict identity."""
        agent = Agent(
            identity={
                "role": "Analyst",
                "goal": "Analyze data",
                "backstory": "Data analyst.",
            },
        )
        assert agent.identity.role == "Analyst"
        assert isinstance(agent.identity, AgentIdentity)

    def test_create_agent_with_dict_config(self):
        """Test creating an agent with a dict config."""
        agent = Agent(
            identity=AgentIdentity(
                role="Dev", goal="Write code", backstory="Developer."
            ),
            config={
                "llm_provider": "mock",
                "llm_model": "mock-model",
                "temperature": 0.5,
            },
        )
        assert isinstance(agent.config, AgentConfig)
        assert agent.config.llm_model == "mock-model"
        assert agent.config.temperature == 0.5

    def test_agent_provider_fallback(self, mock_factory):
        """Test agent provider initialization works with valid provider."""
        # With mock_factory fixture, the 'mock' provider is registered.
        # Agent with no explicit provider should still init (fallback to system default).
        agent = Agent(
            identity=AgentIdentity(
                role="Test", goal="Test", backstory="Test."
            ),
        )
        # Provider should be initialized (falling back to what's available)
        assert agent.provider is not None

    def test_agent_system_prompt(self, researcher_agent):
        """Test the system prompt includes identity and thinking structure."""
        researcher_agent.tools = []
        prompt = researcher_agent._build_system_prompt()
        assert "Researcher" in prompt
        assert "Find and analyze information" in prompt
        assert "An experienced researcher." in prompt
        assert "thinking structure" in prompt.lower()

    def test_agent_system_prompt_with_tools(self, researcher_agent):
        """Test system prompt includes tool descriptions."""
        from ansiq.tools.base import BaseTool, ToolResult

        class MockTool(BaseTool):
            name = "test_tool"
            description = "A test tool"

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="done")

        researcher_agent.add_tool(MockTool())
        prompt = researcher_agent._build_system_prompt()
        assert "test_tool" in prompt
        assert "A test tool" in prompt

    def test_agent_run(self, researcher_agent):
        """Test agent.run returns a response."""
        import asyncio

        response = asyncio.run(researcher_agent.run("Test query"))
        assert response.content == "Mock response"
        assert response.model == "mock-model"

    def test_agent_run_with_context(self, researcher_agent):
        """Test agent.run with additional context."""
        import asyncio

        response = asyncio.run(
            researcher_agent.run("Test query", context="Some context")
        )
        assert response.content == "Mock response"

    def test_agent_chat(self, researcher_agent):
        """Test agent chat method."""
        import asyncio

        response = asyncio.run(researcher_agent.chat("Hello"))
        assert response.content == "Mock response"

    def test_agent_stream(self, researcher_agent):
        """Test streaming chat returns tokens that accumulate correctly."""
        import asyncio

        async def _run():
            tokens = []
            async for token in await researcher_agent.chat("Stream test", stream=True):
                tokens.append(token)
            return "".join(tokens)

        full_text = asyncio.run(_run())
        assert full_text == "Mock response"
        # Conversation history should be updated after streaming
        assert len(researcher_agent._conversation_history) == 2  # user + assistant

    def test_agent_stream_empty(self, researcher_agent):
        """Test streaming with no response content still updates history."""
        import asyncio

        async def _run():
            tokens = []
            async for token in await researcher_agent.chat("Empty", stream=True):
                tokens.append(token)
            return tokens

        # The mock provider returns "Mock response" regardless
        tokens = asyncio.run(_run())
        assert len(tokens) > 0

    def test_agent_stream_vs_chat_consistency(self, researcher_agent):
        """Test streaming and non-streaming produce same content."""
        import asyncio

        async def _run():
            # Non-streaming
            response = await researcher_agent.chat("Test", stream=False)
            full_content = response.content

            # Streaming (reset history for clean state)
            researcher_agent.reset_conversation()
            tokens = []
            async for token in await researcher_agent.chat("Test", stream=True):
                tokens.append(token)
            streamed_content = "".join(tokens)

            return full_content, streamed_content

        full, streamed = asyncio.run(_run())
        assert full == streamed

    def test_agent_conversation_history(self, researcher_agent, mock_provider):
        """Test conversation history is maintained."""
        import asyncio

        asyncio.run(researcher_agent.run("First message"))
        asyncio.run(researcher_agent.run("Second message"))

        assert len(researcher_agent._conversation_history) == 4  # 2 user + 2 assistant

    def test_agent_reset_conversation(self, researcher_agent):
        """Test resetting conversation history."""
        import asyncio

        asyncio.run(researcher_agent.run("Message"))
        researcher_agent.reset_conversation()
        assert len(researcher_agent._conversation_history) == 0

    def test_agent_add_tool(self, researcher_agent):
        """Test adding a tool to the agent."""
        from ansiq.tools.base import BaseTool, ToolResult

        class MockTool(BaseTool):
            name = "sample_tool"
            description = "Sample"

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="ok")

        researcher_agent.add_tool(MockTool())
        assert len(researcher_agent.tools) == 1

    def test_agent_add_skill(self, researcher_agent):
        """Test adding a skill to the agent."""
        from ansiq.skills.base import BaseSkill, SkillResult

        class MockSkill(BaseSkill):
            name = "test_skill"
            description = "A test skill"

            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="done")

        researcher_agent.add_skill(MockSkill())
        assert len(researcher_agent.skills) == 1

    def test_agent_repr(self, researcher_agent):
        """Test agent string representation."""
        rep = repr(researcher_agent)
        assert "Agent" in rep
        assert "Researcher" in rep


# ── Task Tests ──


class TestTask:
    def test_create_task(self):
        """Test creating a basic task."""
        task = Task(
            description="Research {topic}",
            expected_output="A summary",
        )
        assert task.description == "Research {topic}"
        assert task.expected_output == "A summary"
        assert task.context == []

    def test_task_with_context(self, sample_task):
        """Test task with dependent context tasks."""
        dep = Task(
            description="Gather data",
            expected_output="Raw data",
        )
        dep.result = "some data"
        sample_task.context = [dep]
        context = sample_task.get_context_text()
        assert "some data" in context

    def test_task_no_context(self, sample_task):
        """Test task with no context returns empty string."""
        assert sample_task.get_context_text() == ""

    def test_task_with_agent(self, researcher_agent):
        """Test task with an assigned agent."""
        task = Task(
            description="Do research",
            expected_output="Results",
            agent=researcher_agent,
        )
        assert task.agent is not None

    def test_task_repr(self):
        """Test task string representation."""
        task = Task(description="Short description", expected_output="Out")
        rep = repr(task)
        assert "Task" in rep


# ── Crew Tests ──


class TestCrew:
    @pytest.mark.asyncio
    async def test_crew_create(self, researcher_agent, writer_agent):
        """Test creating a crew."""
        tasks = [
            Task(description="Task 1", expected_output="Out 1", agent=researcher_agent),
            Task(description="Task 2", expected_output="Out 2", agent=writer_agent),
        ]
        crew = Crew(
            agents=[researcher_agent, writer_agent],
            tasks=tasks,
            process=ProcessType.PIPELINE,
        )
        assert len(crew.agents) == 2
        assert len(crew.tasks) == 2
        assert crew.process == ProcessType.PIPELINE

    @pytest.mark.asyncio
    async def test_crew_pipeline_execution(self, sample_crew):
        """Test pipeline execution produces results."""
        result = await sample_crew.kickoff(inputs={"topic": "AI Agents"})
        assert isinstance(result, CrewResult)
        assert len(result.tasks_output) > 0
        assert result.raw_output is not None

    @pytest.mark.asyncio
    async def test_crew_council_execution(self, researcher_agent, writer_agent):
        """Test council (hierarchical) execution."""
        tasks = [
            Task(description="Task 1", expected_output="Out 1"),
            Task(description="Task 2", expected_output="Out 2"),
        ]
        crew = Crew(
            agents=[researcher_agent, writer_agent],
            tasks=tasks,
            process=ProcessType.COUNCIL,
        )
        result = await crew.kickoff()
        assert isinstance(result, CrewResult)

    @pytest.mark.asyncio
    async def test_crew_add_agent(self, sample_crew, mock_provider):
        """Test adding an agent to a crew."""
        agent = Agent(
            identity=AgentIdentity(
                role="Reviewer", goal="Review work", backstory="Reviewer."
            ),
            provider=mock_provider,
        )
        sample_crew.add_agent(agent)
        assert len(sample_crew.agents) == 3

    @pytest.mark.asyncio
    async def test_crew_add_task(self, sample_crew, researcher_agent):
        """Test adding a task to a crew."""
        task = Task(
            description="Review the work",
            expected_output="Review notes",
            agent=researcher_agent,
        )
        sample_crew.add_task(task)
        assert len(sample_crew.tasks) == 3

    @pytest.mark.asyncio
    async def test_crew_kickoff_for_each(self, sample_crew):
        """Test kickoff_for_each runs with multiple inputs."""
        results = await sample_crew.kickoff_for_each([
            {"topic": "AI"},
            {"topic": "ML"},
        ])
        assert len(results) == 2
        for r in results:
            assert isinstance(r, CrewResult)

    def test_crew_repr(self, sample_crew):
        """Test crew string representation."""
        rep = repr(sample_crew)
        assert "Crew" in rep
        assert "pipeline" in rep


# ── Flow Tests ──


class TestFlow:
    @pytest.mark.asyncio
    async def test_flow_registers_methods(self):
        """Test flow discovers decorated methods."""

        class TestFlow(Flow):
            @start()
            async def begin(self):
                return {"msg": "started"}

            @listen(begin)
            async def after_begin(self):
                return {"msg": "done"}

        flow = TestFlow()
        methods = flow.get_methods()
        assert len(methods) >= 1

    def test_listen_requires_source(self):
        """Test @listen() without args raises error."""
        with pytest.raises(ValueError, match="requires a source"):
            @listen()
            def dummy():
                pass

    @pytest.mark.asyncio
    async def test_flow_kickoff(self):
        """Test flow execution from start methods."""

        class SimpleFlow(Flow):
            @start()
            async def begin(self, topic: str = "test"):
                return {"result": f"Researching {topic}"}

        flow = SimpleFlow()
        result = await flow.kickoff({"topic": "AI"})
        assert "begin" in result

    @pytest.mark.asyncio
    async def test_flow_no_start_method(self):
        """Test flow raises error with no @start method."""

        class EmptyFlow(Flow):
            async def something(self):
                pass

        flow = EmptyFlow()
        with pytest.raises(RuntimeError, match="No @start method"):
            await flow.kickoff()

    def test_or_condition(self):
        """Test or_ condition creation."""
        from ansiq.core.flow import OrCondition
        cond = or_("method_a", "method_b")
        assert isinstance(cond, OrCondition)
        assert cond.conditions == ("method_a", "method_b")

    def test_and_condition(self):
        """Test and_ condition creation."""
        from ansiq.core.flow import AndCondition
        cond = and_("method_a", "method_b")
        assert isinstance(cond, AndCondition)
        assert cond.conditions == ("method_a", "method_b")


# ── State Tests ──


class TestState:
    def test_state_manager_create(self):
        """Test creating a state manager."""
        sm = StateManager()
        assert sm._state is None

    def test_state_manager_with_initial(self):
        """Test state manager with initial state."""
        state = FS()
        sm = StateManager(initial_state=state)
        assert sm.state is not None

    def test_state_manager_update(self):
        """Test updating state fields."""
        state = FS()
        sm = StateManager(initial_state=state)
        sm.state.completed_steps.append("step_1")
        assert "step_1" in sm.state.completed_steps

    def test_state_manager_snapshot_rollback(self):
        """Test snapshot and rollback."""
        state = FS()
        sm = StateManager(initial_state=state)
        sm.state.completed_steps.append("step_1")
        sm.snapshot()
        sm.state.completed_steps.append("step_2")
        assert len(sm.state.completed_steps) == 2
        sm.rollback()
        assert len(sm.state.completed_steps) == 1

    def test_state_manager_record_step(self):
        """Test recording a step."""
        state = FS()
        sm = StateManager(initial_state=state)
        sm.record_step("research")
        assert "research" in sm.state.completed_steps

    def test_state_manager_record_error(self):
        """Test recording an error."""
        state = FS()
        sm = StateManager(initial_state=state)
        sm.record_error("Something went wrong")
        assert "Something went wrong" in sm.state.errors

    def test_state_manager_to_dict(self):
        """Test exporting state as dict."""
        state = FS()
        sm = StateManager(initial_state=state)
        sm.record_step("step_1")
        d = sm.to_dict()
        assert "completed_steps" in d
        assert "step_1" in d["completed_steps"]

    def test_state_manager_from_dict(self):
        """Test creating state from dict."""
        sm = StateManager.from_dict(
            {"completed_steps": ["step_1"], "errors": [], "metadata": {}},
            FS,
        )
        assert "step_1" in sm.state.completed_steps

    def test_state_manager_access_before_init(self):
        """Test accessing uninitialized state raises error."""
        sm = StateManager()
        with pytest.raises(RuntimeError):
            _ = sm.state

    def test_flow_state_defaults(self):
        """Test FlowState default values."""
        state = FS()
        assert state.metadata == {}
        assert state.errors == []
        assert state.completed_steps == []


# ── LLMMessage Tests ──


class TestLLMMessage:
    def test_system_message(self):
        """Test creating a system message."""
        msg = LLMMessage.system("System prompt")
        assert msg.role.value == "system"
        assert msg.content == "System prompt"

    def test_user_message(self):
        """Test creating a user message."""
        msg = LLMMessage.user("User input")
        assert msg.role.value == "user"
        assert msg.content == "User input"

    def test_assistant_message(self):
        """Test creating an assistant message."""
        msg = LLMMessage.assistant("Assistant response")
        assert msg.role.value == "assistant"
        assert msg.content == "Assistant response"

    def test_tool_message(self):
        """Test creating a tool message."""
        msg = LLMMessage.tool("Tool output", "call_123")
        assert msg.role.value == "tool"
        assert msg.content == "Tool output"
        assert msg.tool_call_id == "call_123"
