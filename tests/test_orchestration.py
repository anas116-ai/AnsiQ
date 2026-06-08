"""Tests for the orchestration module — DAG, TaskGroup, BatchProcessor, ParallelExecutor."""

from __future__ import annotations

import asyncio

import pytest

from ansiq.orchestration.dag import DAG, DAGNode, DAGNodeStatus, DAGResult
from ansiq.orchestration.parallel import BatchProcessor, ParallelExecutor, TaskGroup


class TestDAGNode:
    """Test DAGNode model and execution."""

    def test_create_node(self):
        node = DAGNode(name="test_node", description="A test node")
        assert node.name == "test_node"
        assert node.status == DAGNodeStatus.PENDING
        assert node.depends_on == []
        assert node.retry_count == 0
        assert node.id is not None

    def test_node_with_dependencies(self):
        node = DAGNode(id="task_2", name="Task 2", depends_on=["task_1"],
                       timeout=30.0, retry_count=2, retry_delay=0.5)
        assert node.id == "task_2"
        assert node.depends_on == ["task_1"]
        assert node.timeout == 30.0
        assert node.retry_count == 2

    def test_node_status_values(self):
        assert DAGNodeStatus.PENDING.value == "pending"
        assert DAGNodeStatus.RUNNING.value == "running"
        assert DAGNodeStatus.COMPLETED.value == "completed"
        assert DAGNodeStatus.FAILED.value == "failed"
        assert DAGNodeStatus.SKIPPED.value == "skipped"
        assert DAGNodeStatus.BLOCKED.value == "blocked"


class TestDAG:
    """Test DAG orchestrator creation and validation."""

    def test_create_dag(self):
        dag = DAG("test_dag", description="A test DAG")
        assert dag.name == "test_dag"
        assert len(dag._nodes) == 0

    def test_add_node(self):
        dag = DAG("test")
        node = dag.add_node(DAGNode(id="a", name="A"))
        assert node.id == "a"
        assert dag.get_node("a") is not None

    def test_get_node_by_name(self):
        dag = DAG("test")
        dag.add_node(DAGNode(id="n1", name="Node One"))
        found = dag.get_node("Node One")
        assert found is not None
        assert found.id == "n1"

    def test_get_nonexistent_node(self):
        dag = DAG("test")
        assert dag.get_node("nonexistent") is None

    def test_add_duplicate_node_raises(self):
        dag = DAG("test")
        dag.add_node(DAGNode(id="dup", name="Dup"))
        with pytest.raises(ValueError, match="already exists"):
            dag.add_node(DAGNode(id="dup", name="Dup Again"))

    def test_validate_empty_dag_raises(self):
        dag = DAG("empty")
        with pytest.raises(ValueError, match="no nodes"):
            dag._validate()

    def test_validate_missing_dependency_raises(self):
        dag = DAG("test")
        dag.add_node(DAGNode(id="a", name="A", depends_on=["b"]))
        with pytest.raises(ValueError, match="does not exist"):
            dag._validate()

    def test_validate_cycle_detection(self):
        dag = DAG("cycle_test")
        dag.add_node(DAGNode(id="a", name="A", depends_on=["b"]))
        dag.add_node(DAGNode(id="b", name="B", depends_on=["a"]))
        with pytest.raises(ValueError, match="Circular dependency"):
            dag._validate()

    def test_validate_valid_dag(self):
        dag = DAG("valid")
        dag.add_node(DAGNode(id="a", name="A"))
        dag.add_node(DAGNode(id="b", name="B", depends_on=["a"]))
        dag._validate()

    def test_visualize(self):
        dag = DAG("viz_test")
        dag.add_node(DAGNode(id="a", name="Alpha"))
        dag.add_node(DAGNode(id="b", name="Beta", depends_on=["a"]))
        viz = dag.visualize()
        assert "DAG:" in viz
        assert "Alpha" in viz
        assert "(root)" in viz

    def test_to_dict(self):
        dag = DAG("export_test")
        dag.add_node(DAGNode(id="x", name="X"))
        d = dag.to_dict()
        assert d["name"] == "export_test"
        assert d["nodes"][0]["name"] == "X"

    def test_getitem_access(self):
        dag = DAG("test")
        dag.add_node(DAGNode(id="my_id", name="My Node"))
        node = dag["My Node"]
        assert node is not None
        assert node.id == "my_id"

    def test_repr(self):
        dag = DAG("repr_test")
        dag.add_node(DAGNode(id="a", name="A"))
        rep = repr(dag)
        assert "repr_test" in rep

    def test_empty_execute_raises(self):
        dag = DAG("empty")
        with pytest.raises(ValueError):
            asyncio.run(dag.execute())

    @pytest.mark.asyncio
    async def test_dag_execution_without_agents(self):
        """DAG nodes without agents should fail gracefully."""
        dag = DAG("exec_test")
        dag.add_node(DAGNode(id="a", name="A"))
        dag.add_node(DAGNode(id="b", name="B", depends_on=["a"]))
        result = await dag.execute(max_concurrent=5)
        assert isinstance(result, DAGResult)
        assert result.total_nodes == 2
        # Dependency 'B' depends on 'A', so when 'A' fails, 'B' is skipped
        assert len(result.failed_nodes) == 1
        assert len(result.skipped_nodes) == 1

    @pytest.mark.asyncio
    async def test_dag_with_timeout_fails_gracefully(self):
        """Test DAG with per-node timeout, nodes without agents fail."""
        dag = DAG("timeout_test")
        dag.add_node(DAGNode(id="fast", name="Fast", timeout=5.0))
        result = await dag.execute()
        assert result.total_nodes == 1
        # Node has no agent, so it should fail
        assert len(result.failed_nodes) == 1


class TestDAGResult:
    """Test DAGResult model."""

    def test_default_result(self):
        result = DAGResult()
        assert result.total_nodes == 0
        assert result.is_success is True

    def test_is_success_with_failures(self):
        result = DAGResult(successful_nodes=["a"], failed_nodes=["b"], total_nodes=2)
        assert result.is_success is False

    def test_summary(self):
        result = DAGResult(successful_nodes=["a", "b"], total_nodes=2, execution_time=1.5)
        summary = result.summary
        assert "2 nodes" in summary

    def test_node_statuses(self):
        result = DAGResult(node_statuses={"a": DAGNodeStatus.COMPLETED})
        assert result.node_statuses["a"] == DAGNodeStatus.COMPLETED


class TestTaskGroup:
    """Test TaskGroup for concurrent task execution."""

    @pytest.mark.asyncio
    async def test_create_group(self):
        group = TaskGroup(name="test_group")
        assert group.name == "test_group"

    @pytest.mark.asyncio
    async def test_execute_empty_group(self):
        group = TaskGroup(name="empty")
        results = await group.execute()
        assert results == []

    @pytest.mark.asyncio
    async def test_execute_successful_tasks(self):
        async def task_a():
            return "result_a"

        async def task_b():
            return "result_b"

        group = TaskGroup(name="parallel")
        group.add(task_a).add(task_b)
        results = await group.execute()
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_execute_with_error_non_strict(self):
        async def good_task():
            return "ok"

        async def bad_task():
            raise ValueError("task failed")

        group = TaskGroup(name="non_strict", strict=False)
        group.add(good_task).add(bad_task)
        results = await group.execute()
        # Non-strict: errors are caught silently
        # results only contains outputs of successfully completed tasks
        # The good task returns "ok", the bad task's exception is swallowed
        assert len(results) == 1
        assert "ok" in results

    @pytest.mark.asyncio
    async def test_execute_with_error_strict(self):
        async def good_task():
            return "ok"

        async def bad_task():
            raise ValueError("strict failure")

        group = TaskGroup(name="strict", strict=True)
        group.add(good_task).add(bad_task)
        with pytest.raises(ValueError):
            await group.execute()


class TestBatchProcessor:
    """Test BatchProcessor for parallel item processing."""

    @pytest.mark.asyncio
    async def test_process_empty(self):
        processor = BatchProcessor(max_concurrent=5)
        results = await processor.process([], handler=lambda x: x)
        assert results == []

    @pytest.mark.asyncio
    async def test_process_items(self):
        async def double(x):
            return x * 2

        processor = BatchProcessor(max_concurrent=10)
        results = await processor.process([1, 2, 3], handler=double)
        assert results == [2, 4, 6]

    @pytest.mark.asyncio
    async def test_process_with_retries(self):
        attempts = [0]

        async def fails_once(x):
            attempts[0] += 1
            if attempts[0] < 2:
                raise ValueError("temporary failure")
            return x

        processor = BatchProcessor(max_concurrent=5, retry_count=2, retry_delay=0.01)
        results = await processor.process([1], handler=fails_once)
        assert results == [1]

    @pytest.mark.asyncio
    async def test_process_with_rate_limit(self):
        async def echo(x):
            return x

        processor = BatchProcessor(max_concurrent=5, rate_limit=0.01)
        results = await processor.process([1, 2, 3], handler=echo)
        assert results == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_process_stream(self):
        async def echo(x):
            return x

        processor = BatchProcessor(max_concurrent=10)
        results = []
        async for idx, result in processor.process_stream([1, 2, 3], handler=echo):
            results.append((idx, result))
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_progress_callback(self):
        progress_log = []

        async def echo(x):
            return x

        def progress(completed, total):
            progress_log.append((completed, total))

        processor = BatchProcessor(max_concurrent=10)
        await processor.process([1, 2, 3], handler=echo, progress_callback=progress)
        assert len(progress_log) == 3
        assert progress_log[-1] == (3, 3)


class TestParallelExecutor:
    """Test ParallelExecutor for managing task groups."""

    @pytest.mark.asyncio
    async def test_create_executor(self):
        executor = ParallelExecutor(max_workers=10)
        assert executor.max_workers == 10

    @pytest.mark.asyncio
    async def test_execute_groups_parallel(self):
        async def task_a():
            return "A"
        async def task_b():
            return "B"

        group1 = TaskGroup(name="group1")
        group1.add(task_a)
        group2 = TaskGroup(name="group2")
        group2.add(task_b)

        executor = ParallelExecutor(max_workers=10)
        results = await executor.execute_groups([group1, group2])
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_execute_groups_sequential(self):
        async def task_a():
            return "A"

        group1 = TaskGroup(name="seq_group")
        group1.add(task_a)

        executor = ParallelExecutor(max_workers=10)
        results = await executor.execute_groups([group1], sequential=True)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_get_stats(self):
        executor = ParallelExecutor()
        stats = executor.get_stats()
        assert stats["total_groups"] == 0

    @pytest.mark.asyncio
    async def test_reset_stats(self):
        executor = ParallelExecutor()
        executor._stats["total_groups"] = 5
        executor.reset_stats()
        assert executor._stats["total_groups"] == 0
