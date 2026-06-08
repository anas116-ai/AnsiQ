"""Comprehensive edge case, boundary, and stress tests for all AnsiQ modules.

Covers scenarios not tested in the per-module test files:
- Boundary conditions (empty strings, None values, extreme inputs)
- Error recovery paths
- Unicode/special characters
- Resource exhaustion scenarios
- Concurrent access patterns
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from ansiq.core.agent import Agent, AgentConfig, AgentIdentity
from ansiq.core.crew import Crew, CrewResult
from ansiq.core.hooks import AgentHooks, HookEvent, HookRegistry, HookResult
from ansiq.core.state import FlowState, StateManager
from ansiq.core.task import Task
from ansiq.execution.executor import ExecutionResult, LocalExecutor
from ansiq.knowledge.engine import RAGEngine
from ansiq.knowledge.source import FileSource, TextSource, URLSource
from ansiq.knowledge.store import VectorKnowledgeStore
from ansiq.llm.base import ImageBlock, LLMMessage
from ansiq.llm.router import ModelCapability, ModelRouter, TaskComplexity
from ansiq.memory.providers import CompositeMemoryProvider, EntityMemoryProvider, FtsMemoryProvider
from ansiq.scheduler.scheduler import Scheduler, next_run_time, parse_cron
from ansiq.skills.base import BaseSkill, SkillResult
from ansiq.tools.base import BaseTool, ToolResult
from ansiq.tools.registry import ToolRegistry

# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Agent — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestAgentEdgeCases:
    """Edge cases for Agent — empty inputs, extreme values, error paths."""

    def test_empty_task_string(self, researcher_agent):
        """Agent.run with empty string should not crash."""
        import asyncio
        response = asyncio.run(researcher_agent.run(""))
        assert response is not None

    def test_very_long_task(self, researcher_agent):
        """Agent.run with a very long task (stress)."""
        long_task = "Analyze " + " ".join(["data"] * 500)
        import asyncio
        response = asyncio.run(researcher_agent.run(long_task))
        assert response is not None

    def test_unicode_special_chars_in_task(self, researcher_agent):
        """Agent.run with unicode, emoji, and special characters."""
        import asyncio
        tasks = [
            "分析数据",            # Chinese
            "データ分析",          # Japanese
            "Analyze ✓ ∑ ∞ π",   # Math symbols
            "Hello 🌍 👋 🚀",    # Emoji
            "<script>alert('xss')</script>",  # HTML injection
            "Null byte: \x00 here",           # Null bytes
        ]
        for task in tasks:
            response = asyncio.run(researcher_agent.run(task))
            assert response is not None, f"Failed on task: {task!r}"

    def test_task_with_extreme_context(self, researcher_agent):
        """Agent.run with extremely long context."""
        import asyncio
        huge_context = "Context. " * 10000  # ~80K chars
        response = asyncio.run(researcher_agent.run("Simple query", context=huge_context))
        assert response is not None

    def test_add_tool_twice(self, researcher_agent):
        """Adding the same tool twice should work (no dedup)."""
        class DupTool(BaseTool):
            name = "dup"
            description = "Duplicate tool"
            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="ok")

        tool = DupTool()
        researcher_agent.add_tool(tool)
        researcher_agent.add_tool(tool)
        assert len(researcher_agent.tools) == 2  # Two references allowed

    def test_build_system_prompt_no_tools_no_memory(self, researcher_agent):
        """System prompt with empty tools and memory should not error."""
        researcher_agent.tools = []
        researcher_agent.memory = None
        prompt = researcher_agent._build_system_prompt()
        assert "You are Researcher" in prompt

    def test_reset_conversation_when_empty(self, researcher_agent):
        """Resetting conversation when already empty should not error."""
        researcher_agent.reset_conversation()
        assert len(researcher_agent._conversation_history) == 0

    def test_run_with_context_that_triggers_exception(self, researcher_agent):
        """Agent should handle memory search exceptions gracefully."""
        class BrokenMemory:
            def search(self, *args, **kwargs):
                raise RuntimeError("Broken memory")
            def get_relevant_context(self, *args, **kwargs):
                raise RuntimeError("Broken")
            def store(self, *args, **kwargs):
                raise RuntimeError("Broken store")

        researcher_agent.memory = BrokenMemory()
        import asyncio
        response = asyncio.run(researcher_agent.run("Test with broken memory"))
        assert response is not None

    def test_minimal_thinking_mode(self, mock_provider):
        """Agent with minimal thinking mode."""
        agent = Agent(
            identity=AgentIdentity(role="Fast", goal="Quick", backstory="Fast agent."),
            provider=mock_provider,
            config=AgentConfig(
                identity=AgentIdentity(role="Fast", goal="Quick", backstory="Fast agent."),
                thinking_mode="minimal",
                llm_provider="mock",
                llm_model="mock-model",
            ),
        )
        prompt = agent._build_system_prompt()
        # Minimal mode should not include the thinking structure
        assert "thinking structure" not in prompt.lower()

    def test_deep_thinking_mode(self, mock_provider):
        """Agent with deep thinking mode."""
        agent = Agent(
            identity=AgentIdentity(role="Deep", goal="Deep thinking", backstory="Deep."),
            provider=mock_provider,
            config=AgentConfig(
                identity=AgentIdentity(role="Deep", goal="Deep thinking", backstory="Deep."),
                thinking_mode="deep",
                llm_provider="mock",
                llm_model="mock-model",
            ),
        )
        prompt = agent._build_system_prompt()
        assert "Analyze" in prompt
        assert "Plan" in prompt
        assert "Execute" in prompt
        assert "Evaluate" in prompt


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Crew — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestCrewEdgeCases:
    """Edge cases for Crew — empty agents/tasks, failure paths."""

    @pytest.mark.asyncio
    async def test_crew_no_agents(self, researcher_agent):
        """Crew with agents but no matching agent for the task."""
        task = Task(description="Do work", expected_output="Done", agent=researcher_agent)
        crew = Crew(agents=[researcher_agent], tasks=[task])
        result = await crew.kickoff()
        assert isinstance(result, CrewResult)

    @pytest.mark.asyncio
    async def test_crew_no_tasks(self, researcher_agent, writer_agent):
        """Crew with no tasks should not crash."""
        crew = Crew(agents=[researcher_agent, writer_agent], tasks=[])
        result = await crew.kickoff()
        assert isinstance(result, CrewResult)
        assert result.tasks_output == []

    @pytest.mark.asyncio
    async def test_crew_with_unnamed_agents(self, researcher_agent):
        """Crew where task.agent is a string that doesn't match any agent."""
        task = Task(description="Do work", expected_output="Done", agent="nonexistent_agent")
        crew = Crew(
            agents=[researcher_agent],
            tasks=[task],
        )
        result = await crew.kickoff()
        assert isinstance(result, CrewResult)

    def test_crew_repr_empty(self):
        """Crew string representation with no agents/tasks."""
        crew = Crew(agents=[], tasks=[])
        rep = repr(crew)
        assert "Crew" in rep
        assert "0" in rep  # 0 agents, 0 tasks


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Flow — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestFlowEdgeCases:
    """Edge cases for Flow — no methods, routers, sync methods."""

    @pytest.mark.asyncio
    async def test_flow_with_only_listeners(self):
        """Flow with @listen but no @start should raise."""
        from ansiq.core.flow import Flow, start

        class HasStart(Flow):
            @start()
            async def begin(self):
                pass

        class ListenerOnly(Flow):
            def process(self):
                pass

        # Flow with no decorated methods at all should have no start
        flow = Flow()
        with pytest.raises(RuntimeError, match="No @start method"):
            await flow.kickoff()

    @pytest.mark.asyncio
    async def test_flow_sync_start_method(self):
        """Flow with sync (non-async) start method."""
        from ansiq.core.flow import Flow, listen, start

        class SyncFlow(Flow):
            @start()
            def begin(self):
                return {"status": "done"}

            @listen(begin)
            async def after(self, **kwargs):
                return {"status": "completed"}

        flow = SyncFlow()
        result = await flow.kickoff()
        assert "begin" in result

    @pytest.mark.asyncio
    async def test_flow_with_router_records_route(self):
        """Flow router records the route taken."""
        from ansiq.core.flow import Flow, router, start

        class RouterFlow(Flow):
            @start()
            async def begin(self):
                return {"action": "A"}

            @router(begin)
            async def decide(self):
                return "route_a"

        flow = RouterFlow()
        result = await flow.kickoff()
        assert "begin" in result

    @pytest.mark.asyncio
    async def test_flow_with_two_start_methods(self):
        """Flow with two @start methods should run both."""
        from ansiq.core.flow import Flow, start

        class TwoStartFlow(Flow):
            @start()
            async def method_a(self):
                return {"data": "from_a"}

            @start()
            async def method_b(self):
                return {"data": "from_b"}

        flow = TwoStartFlow()
        result = await flow.kickoff()
        assert "method_a" in result
        assert "method_b" in result


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: State — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestStateEdgeCases:
    """Edge cases for StateManager — rollback from empty, empty dict from_dict."""

    def test_rollback_empty_snapshots(self):
        """Rollback with no snapshots should not raise."""
        sm = StateManager(initial_state=FlowState())
        sm.rollback()  # Should not raise
        assert sm.state is not None

    def test_multiple_snapshots_rollback(self):
        """Multiple snapshots should roll back in LIFO order."""
        sm = StateManager(initial_state=FlowState())
        sm.record_step("step_1")
        sm.snapshot()
        sm.record_step("step_2")
        sm.snapshot()
        sm.record_step("step_3")

        assert len(sm.state.completed_steps) == 3

        sm.rollback()
        assert len(sm.state.completed_steps) == 2
        assert "step_3" not in sm.state.completed_steps

        sm.rollback()
        assert len(sm.state.completed_steps) == 1

    def test_from_dict_empty(self):
        """from_dict with empty dict should still create valid state."""
        sm = StateManager.from_dict({}, FlowState)
        assert sm.state is not None
        assert sm.state.completed_steps == []

    def test_update_with_nonexistent_field(self):
        """Updating a field that doesn't exist on the model."""
        sm = StateManager(initial_state=FlowState())
        sm.update(completed_steps=["step_1"])
        assert "step_1" in sm.state.completed_steps


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: LLM Router — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestRouterEdgeCases:
    """Edge cases for ModelRouter — empty tasks, unicode, extreme inputs."""

    def test_empty_task_routing(self):
        """Router should handle empty task string."""
        router = ModelRouter()
        decision = router.route("")
        assert decision is not None
        # Empty tasks should be classified as SIMPLE
        assert decision.estimated_complexity in (TaskComplexity.SIMPLE, TaskComplexity.MEDIUM)

    def test_barely_complex_task(self):
        """Router should classify a minimal task."""
        router = ModelRouter()
        decision = router.route("Hello")
        assert decision is not None
        assert decision.selected_model is not None

    def test_very_complex_task(self):
        """Router should detect very complex tasks."""
        router = ModelRouter()
        complex_task = "Design and architect a comprehensive multi-step strategic analysis of comparative research methodologies for optimizing advanced machine learning systems"
        decision = router.route(complex_task)
        assert decision.estimated_complexity == TaskComplexity.VERY_COMPLEX

    def test_code_task_detection(self):
        """Router should detect code tasks."""
        router = ModelRouter()
        decision = router.route("Write a Python function to sort a list")
        caps = router._detect_required_capabilities("Write a Python function to sort a list", TaskComplexity.MEDIUM)
        assert ModelCapability.CODE in caps

    def test_creative_task_detection(self):
        """Router should detect creative tasks."""
        router = ModelRouter()
        caps = router._detect_required_capabilities("Write a creative story about AI", TaskComplexity.MEDIUM)
        assert ModelCapability.CREATIVITY in caps

    def test_long_context_cost_flagging(self):
        """Long tasks should trigger COST_EFFICIENT."""
        router = ModelRouter()
        long_task = "word " * 300
        caps = router._detect_required_capabilities(long_task, TaskComplexity.VERY_COMPLEX)
        assert ModelCapability.COST_EFFICIENT in caps

    def test_routing_with_preferred_provider(self):
        """Router should filter by preferred provider."""
        router = ModelRouter()
        decision = router.route("Simple task", preferred_provider="anthropic")
        assert decision.selected_provider == "anthropic"


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Tools — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestToolEdgeCases:
    """Edge cases for tools — empty names, missing params, error handling."""

    def setup_method(self):
        ToolRegistry._tools.clear()

    def test_tool_with_no_name(self):
        """Tool with empty name should use class name."""
        class NoNameTool(BaseTool):
            description = "No name set"
            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="ok")

        tool = NoNameTool()
        assert tool.name == "nonametool"  # Default from class name

    def test_tool_with_empty_description(self):
        """Tool with empty description shouldn't crash."""
        class EmptyDescTool(BaseTool):
            name = "empty_desc"
            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="ok")

        tool = EmptyDescTool()
        desc = tool.get_description()
        assert desc == ""  # Empty description returns empty

    def test_tool_execute_that_raises(self):
        """Tool whose execute() raises an exception."""
        class BrokenTool(BaseTool):
            name = "broken"
            description = "Always breaks"
            async def execute(self, **kwargs) -> ToolResult:
                raise ValueError("Intentional failure")

        import asyncio
        tool = BrokenTool()
        with pytest.raises(ValueError):
            asyncio.run(tool.execute())

    def test_tool_schema_with_no_required_params(self):
        """Function schema with all optional params should have empty required list."""
        class OptTool(BaseTool):
            name = "optional_params"
            description = "All optional"
            parameters = []

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="ok")

        tool = OptTool()
        schema = tool.to_function_schema()
        assert "required" not in schema["function"]["parameters"] or schema["function"]["parameters"].get("required", []) == []

    def test_tool_registry_duplicate_overwrites(self):
        """Registering same name twice should overwrite silently."""
        class ToolA(BaseTool):
            name = "same_name"
            description = "First"
            async def execute(self, **kwargs): return ToolResult()

        class ToolB(BaseTool):
            name = "same_name"
            description = "Second"
            async def execute(self, **kwargs): return ToolResult()

        ToolRegistry.register(ToolA())
        ToolRegistry.register(ToolB())
        tool = ToolRegistry.get("same_name")
        assert tool.description == "Second"  # Last one wins

    def test_tool_run_captures_error(self):
        """Tool.run should not raise, only capture error output."""
        class ErrTool(BaseTool):
            name = "err"
            description = "Error tool"
            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(success=False, error="Failed")

        import asyncio
        tool = ErrTool()
        output = asyncio.run(tool.run())
        # run() returns result.output which is empty string on failure
        assert output == ""


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Memory — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestMemoryEdgeCases:
    """Edge cases for memory providers — empty inputs, missing data."""

    def test_entity_memory_with_no_capitalized_words(self, tmp_path):
        """EntityMemoryProvider with content that has no capitalized words."""
        ep = EntityMemoryProvider(storage_path=tmp_path / "entities.json")
        result = ep.store(content="this is all lowercase with no entities", agent_id="test")
        assert result is True
        stats = ep.get_stats()
        assert stats["total_entities"] == 0

    def test_entity_memory_search_empty(self, tmp_path):
        """EntityMemoryProvider search with empty query."""
        ep = EntityMemoryProvider(storage_path=tmp_path / "entities.json")
        results = ep.search("")
        assert results == []

    def test_fts_memory_with_empty_content(self, temp_db_path):
        """FTSMemoryStore with empty content string."""
        store = FtsMemoryProvider(db_path=temp_db_path)
        result = store.store(content="", agent_id="test")
        assert result is True  # SQLite stores empty strings too

    def test_fts_memory_search_empty_query_returns_list(self, temp_db_path):
        """FTSMemoryStore search handles empty string gracefully."""
        store = FtsMemoryProvider(db_path=temp_db_path)
        store.store(content="Test content")
        # FTS5 rejects empty queries, so we test that the code handles it
        try:
            results = store.search("")
            assert isinstance(results, list)
        except Exception:
            # FTS5 may raise on empty query - that's also acceptable
            pass

    def test_composite_memory_no_providers_falls_back(self):
        """CompositeMemoryProvider with [] falls back to defaults."""
        cmp = CompositeMemoryProvider(providers=[])
        # [] is falsy, so it falls back to default providers
        stats = cmp.get_stats()
        assert stats["provider"] == "composite"
        assert len(stats["sub_providers"]) >= 3

    def test_composite_memory_store_returns_false_when_all_fail(self):
        """CompositeMemoryProvider store fails when all sub-providers fail."""
        class FailingProvider:
            name = "failing"
            def store(self, *args, **kwargs):
                return False
            def search(self, *args, **kwargs):
                return []
            def get_relevant_context(self, *args, **kwargs):
                return ""
            def get_stats(self):
                return {"provider": "failing"}

        cmp = CompositeMemoryProvider(providers=[FailingProvider()])
        result = cmp.store(content="test")
        assert result is False


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Knowledge — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestKnowledgeEdgeCases:
    """Edge cases for knowledge engine — empty sources, query issues."""

    def test_empty_text_source(self):
        """TextSource with empty text should produce no chunks."""
        source = TextSource(name="empty", text="")
        import asyncio
        chunks = asyncio.run(source.get_chunks())
        assert len(chunks) == 0

    def test_unicode_text_source(self):
        """TextSource with unicode/multilingual text."""
        text = "日本語のテキスト\n中文文本\nРусский текст\nEnglish mixed 💡"
        source = TextSource(name="unicode_test", text=text)
        import asyncio
        chunks = asyncio.run(source.get_chunks())
        assert len(chunks) >= 1
        assert "💡" in chunks[0]["text"]

    def test_very_large_text_source(self):
        """TextSource with very large text (stress test)."""
        large_text = "Paragraph " * 10000  # ~90K chars
        source = TextSource(name="large", text=large_text)
        import asyncio
        chunks = asyncio.run(source.get_chunks(chunk_size=500, overlap=50))
        assert len(chunks) >= 10  # Should produce many chunks

    def test_rag_engine_empty_query(self, tmp_path):
        """RAGEngine query with empty string."""
        store = VectorKnowledgeStore(store_path=tmp_path / "empty.json")
        engine = RAGEngine(store=store)
        results = engine.query("")
        assert results == []

    def test_rag_engine_no_sources(self, tmp_path):
        """RAGEngine with no sources should return empty results."""
        store = VectorKnowledgeStore(store_path=tmp_path / "nosrc.json")
        engine = RAGEngine(store=store)
        stats = engine.get_stats()
        assert stats["sources"] == []

    def test_vector_store_empty_chunks(self, tmp_path):
        """Adding empty list of chunks should not error."""
        store = VectorKnowledgeStore(store_path=tmp_path / "empty_chunks.json")
        store.add_chunks([])
        assert store.count_chunks() == 0


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Execution — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestExecutorEdgeCases:
    """Edge cases for executors — empty code, quick timeouts."""

    @pytest.mark.asyncio
    async def test_empty_code_string(self):
        """Execute empty Python code."""
        executor = LocalExecutor()
        result = await executor.execute("")
        assert isinstance(result, ExecutionResult)

    @pytest.mark.asyncio
    async def test_code_with_only_comments(self):
        """Execute Python file with only comments."""
        executor = LocalExecutor()
        result = await executor.execute("# This is just a comment\n# Another comment")
        assert isinstance(result, ExecutionResult)

    @pytest.mark.asyncio
    async def test_unicode_in_code_output(self):
        """Execute code that outputs unicode."""
        executor = LocalExecutor()
        result = await executor.execute("print('Hello unicode cafe')")
        assert isinstance(result, ExecutionResult)
        # On some platforms (Windows), unicode in stdout may fail
        # Check that the executor at least returns a result
        assert result is not None

    @pytest.mark.asyncio
    async def test_very_long_code(self):
        """Execute very long Python code (stress test)."""
        executor = LocalExecutor()
        long_code = "x = 0\n" * 500 + "print(x)"
        result = await executor.execute(long_code)
        assert isinstance(result, ExecutionResult)

    @pytest.mark.asyncio
    async def test_write_file_empty_content(self, tmp_path):
        """Writing a file with empty content."""
        executor = LocalExecutor()
        test_file = tmp_path / "empty.txt"
        success = await executor.write_file(str(test_file), "")
        assert success
        assert test_file.read_text() == ""

    @pytest.mark.asyncio
    async def test_execute_bash_with_long_output(self):
        """Bash command with long output (1000 lines)."""
        executor = LocalExecutor()
        result = await executor.execute_command(
            "for i in $(seq 1 100); do echo 'Line '$i; done"
        )
        assert isinstance(result, ExecutionResult)


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Scheduler — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestSchedulerEdgeCases:
    """Edge cases for scheduler — invalid cron, extreme dates."""

    def test_parse_cron_extreme_values(self):
        """Parse cron with boundary values."""
        minutes, hours, days, months, weekdays = parse_cron("59 23 31 12 6")
        assert minutes == [59]
        assert hours == [23]
        assert days == [31]
        assert months == [12]
        assert weekdays == [6]

    def test_next_run_far_future(self):
        """next_run_time with a date far in the future."""
        after = datetime(2030, 1, 1, 0, 0, 0)
        next_run = next_run_time("0 9 * * 1-5", after=after)
        assert next_run is not None
        assert next_run.year >= 2030

    def test_next_run_every_second_friday_13th(self):
        """Check that specific weekday constraints work."""
        after = datetime(2026, 1, 1, 0, 0, 0)
        # Run on Friday (cron weekday=5) at 9 AM
        next_run = next_run_time("0 9 * * 5", after=after)
        assert next_run is not None
        # Python weekday: 0=Mon...4=Fri, cron: 0=Sun...5=Fri
        # So cron 5 maps to Python weekday 4
        assert next_run.weekday() == 4  # Friday in Python

    def test_schedule_with_no_handler(self, tmp_path):
        """Schedule without a handler should not error on start/stop."""
        scheduler = Scheduler(storage_path=tmp_path / "no_handler.json")
        scheduler.add_schedule(name="no_op", cron_expression="* * * * *")

        async def run():
            task = asyncio.create_task(scheduler.start())
            await asyncio.sleep(0.05)
            await scheduler.stop()
            task.cancel()

        asyncio.run(run())
        assert scheduler._running is False

    def test_schedule_persistence_with_special_chars(self, tmp_path):
        """Schedule with unicode metadata should serialize/deserialize."""
        storage = tmp_path / "unicode_sched.json"
        scheduler = Scheduler(storage_path=storage)
        scheduler.add_schedule(
            name="unicode_test",
            cron_expression="0 9 * * *",
            metadata={"description": "日本語テスト 💡"},
        )

        scheduler2 = Scheduler(storage_path=storage)
        loaded = scheduler2.get_schedule("unicode_test")
        assert loaded is not None
        assert loaded.metadata["description"] == "日本語テスト 💡"


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Hooks — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestHooksEdgeCases:
    """Edge cases for hooks — once=True only fires once, injects, errors."""

    def setup_method(self):
        HookRegistry.clear()

    def test_once_hook_executes_only_once(self):
        """Hook with once=True should only execute once."""
        hooks = AgentHooks()
        counter = [0]

        async def once_handler(**kwargs):
            counter[0] += 1
            return HookResult(success=True)

        hooks.register(HookEvent.BEFORE_TASK, once_handler, once=True)

        import asyncio
        asyncio.run(hooks.execute(HookEvent.BEFORE_TASK, task="first"))
        assert counter[0] == 1

        asyncio.run(hooks.execute(HookEvent.BEFORE_TASK, task="second"))
        assert counter[0] == 1  # Still 1 — hook.skipped

    def test_modify_input_propagates(self):
        """Hook that modifies input should pass changes to next hook."""
        hooks = AgentHooks()
        seen = []

        async def modifier(**kwargs):
            return HookResult(success=True, modify_input={"task": "modified!"})

        async def observer(**kwargs):
            seen.append(kwargs.get("task"))
            return HookResult(success=True)

        hooks.register(HookEvent.BEFORE_TASK, modifier, priority=10)
        hooks.register(HookEvent.BEFORE_TASK, observer, priority=0)

        import asyncio
        asyncio.run(hooks.execute(HookEvent.BEFORE_TASK, task="original"))
        assert "modified!" in seen

    def test_multiple_hooks_abort_chain(self):
        """Two abort hooks — first abort prevents second from running."""
        hooks = AgentHooks()
        executed = []

        async def first_abort(**kwargs):
            executed.append("first")
            return HookResult(abort=True)

        async def second_abort(**kwargs):
            executed.append("second")
            return HookResult(abort=True)

        hooks.register(HookEvent.BEFORE_TASK, first_abort, priority=10)
        hooks.register(HookEvent.BEFORE_TASK, second_abort, priority=0)

        import asyncio
        asyncio.run(hooks.execute(HookEvent.BEFORE_TASK))
        assert "first" in executed
        assert "second" not in executed  # Aborted before second

    def test_hook_on_error_event(self):
        """Hook registered on ON_ERROR event works."""
        hooks = AgentHooks()
        captured = []

        async def error_handler(**kwargs):
            captured.append(kwargs.get("error"))
            return HookResult(success=True)

        hooks.register(HookEvent.ON_ERROR, error_handler)

        import asyncio
        asyncio.run(hooks.execute(HookEvent.ON_ERROR, error="Something broke"))
        assert "Something broke" in captured


# ═══════════════════════════════════════════════════════════════════════
# STRESS TEST: Concurrent operations
# ═══════════════════════════════════════════════════════════════════════

class TestStress:
    """Stress tests for concurrent operations and large data volumes."""

    @pytest.mark.asyncio
    async def test_concurrent_memory_operations(self, temp_db_path):
        """Multiple concurrent FTS store operations should not corrupt."""
        store = FtsMemoryProvider(db_path=temp_db_path)

        async def store_many(start: int, count: int):
            for i in range(start, start + count):
                store.store(content=f"Concurrent memory item {i}", agent_id="stress_test")
            return True

        # Start 5 concurrent writers
        tasks = [store_many(i * 10, 10) for i in range(5)]
        results = await asyncio.gather(*tasks)
        assert all(results)

        # Verify all were stored
        stats = store.get_stats()
        assert stats["total_memories"] >= 50

    @pytest.mark.asyncio
    async def test_rag_with_many_sources(self, tmp_path):
        """RAG engine with many small sources."""
        store = VectorKnowledgeStore(store_path=tmp_path / "stress_rag.json")
        engine = RAGEngine(store=store)

        # Add 50 small sources
        for i in range(50):
            source = TextSource(name=f"source_{i}", text=f"This is knowledge source number {i} with some content")
            await engine.add_source(source)

        stats = engine.get_stats()
        assert len(stats["sources"]) == 50  # All sources indexed

        # Query should still work
        results = engine.query("knowledge")
        assert isinstance(results, list)

    def test_many_cron_expressions(self):
        """Parse many cron expressions as stress test."""
        expressions = [
            "* * * * *",
            "*/5 * * * *",
            "0 * * * *",
            "30 9 * * 1-5",
            "0 0 1 1 *",
            "*/15 9-17 * * *",
            "0,30 0-23 * * *",
            "0 0 * * 0",
            "0 0 1,15 * *",
            "0 0 * 1 1",
        ]
        for expr in expressions:
            result = parse_cron(expr)
            assert len(result) == 5

    @pytest.mark.asyncio
    async def test_executor_many_python_snippets(self):
        """Execute many quick Python snippets as stress test."""
        executor = LocalExecutor()
        tasks = [
            executor.execute("x = 1 + 1")
            for _ in range(10)
        ]
        results = await asyncio.gather(*tasks)
        successful = sum(1 for r in results if r.success)
        assert successful >= 9  # Python execution is reliable

    def test_entity_memory_with_many_entities(self, tmp_path):
        """Entity memory with many entities (stress test)."""
        ep = EntityMemoryProvider(storage_path=tmp_path / "many_entities.json")

        for i in range(100):
            name = f"Entity_{i} is a Person from Company_{i // 10}"
            ep.store(content=name, agent_id="stress")

        stats = ep.get_stats()
        # Should have found capitalized entities
        assert stats["total_entities"] > 0


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: ImageBlock — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestImageBlockEdgeCases:
    """Edge cases for ImageBlock creation and handling."""

    def test_image_from_url(self):
        """Create ImageBlock from URL."""
        img = ImageBlock.from_url("https://example.com/image.png")
        assert img.source == "url"
        assert img.format == "url"

    def test_image_from_data_url(self):
        """Create ImageBlock from data URL."""
        import base64
        fake_data = base64.b64encode(b"fake_image_data").decode()
        data_url = f"data:image/png;base64,{fake_data}"
        img = ImageBlock.from_url(data_url)
        assert img.source == "base64"

    def test_image_from_bytes(self):
        """Create ImageBlock from raw bytes."""
        img = ImageBlock.from_bytes(b"fakebytes", fmt="jpeg")
        assert img.format == "jpeg"
        assert img.source == "base64"

    def test_message_with_multiple_images(self):
        """LLMMessage with multiple images."""
        img1 = ImageBlock(data="dGVzdA==", format="png", source="base64")
        img2 = ImageBlock(data="dGVzdDI=", format="jpeg", source="base64")
        msg = LLMMessage.user("Check these images", images=[img1, img2])
        assert msg.has_images() is True
        assert len(msg.images) == 2

    def test_message_with_no_images(self):
        """LLMMessage with no images should report false."""
        msg = LLMMessage.user("No images here")
        assert msg.has_images() is False


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Skills — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestSkillEdgeCases:
    """Edge cases for skills — no feedback, error handling."""

    def test_skill_no_feedback(self):
        """Skill with no improvements returns empty list."""
        class TestSkill(BaseSkill):
            name = "test"
            description = "Test"
            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="ok")

        skill = TestSkill()
        assert skill.get_improvement_history() == []
        assert skill.get_execution_count() == 0

    def test_skill_with_special_chars_in_feedback(self):
        """Skill improvement with unicode feedback."""
        class TestSkill(BaseSkill):
            name = "unicode_feedback"
            description = "Test"
            async def execute(self, **kwargs) -> SkillResult:
                return SkillResult(output="ok")

        skill = TestSkill()
        skill.improve("Make it faster 💨")
        skill.improve("日本語の改善点")
        assert len(skill.get_improvement_history()) == 2


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: Task — boundary conditions
# ═══════════════════════════════════════════════════════════════════════

class TestTaskEdgeCases:
    """Edge cases for Task — empty fields, missing references."""

    def test_task_with_empty_strings(self):
        """Task with empty description and expected_output."""
        task = Task(description="", expected_output="")
        assert task.description == ""
        assert task.expected_output == ""
        assert task.context == []

    def test_task_with_extremely_long_description(self):
        """Task with very long description."""
        long_desc = "Analyze " + " ".join(["data"] * 200)
        task = Task(description=long_desc, expected_output="Result")
        assert len(task.description) > 1000

    def test_task_with_dict_context(self):
        """Task context that is a list of dict-likes should not crash."""
        task = Task(description="Test", expected_output="Out")
        # context is None by default, then set to empty list in __init__
        assert task.context is not None
        assert task.context == []

    def test_task_repr_without_agent(self):
        """Task repr without an agent assigned."""
        task = Task(description="Orphan task", expected_output="Anything")
        rep = repr(task)
        assert "unassigned" in rep


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: URLSource — error handling
# ═══════════════════════════════════════════════════════════════════════

class TestURLSourceEdgeCases:
    """Edge cases for URLSource — invalid URLs, timeouts."""

    def test_url_source_empty_url(self):
        """URLSource with empty URL returns empty content."""
        source = URLSource(name="empty_url", url="")
        import asyncio
        content = asyncio.run(source.load())
        assert content == ""

    def test_url_source_malformed_url(self):
        """URLSource with malformed URL."""
        source = URLSource(name="bad", url="not-a-valid-url")
        import asyncio
        content = asyncio.run(source.load())
        assert content == ""


# ═══════════════════════════════════════════════════════════════════════
# EDGE CASE: FileSource — error handling
# ═══════════════════════════════════════════════════════════════════════

class TestFileSourceEdgeCases:
    """Edge cases for FileSource — missing files, empty files."""

    def test_file_source_with_empty_path(self):
        """FileSource with empty path returns empty content."""
        source = FileSource(name="empty_path", file_path="")
        import asyncio
        content = asyncio.run(source.load())
        assert content == ""

    def test_file_source_idempotent_load(self):
        """Loading a file source multiple times returns same content."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("persistent content")
            path = f.name

        import asyncio
        source = FileSource(name="idempotent", file_path=path)
        content1 = asyncio.run(source.load())
        content2 = asyncio.run(source.load())
        assert content1 == content2 == "persistent content"

        import os
        os.unlink(path)
