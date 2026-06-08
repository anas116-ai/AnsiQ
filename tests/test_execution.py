"""Tests for execution environments — LocalExecutor."""

from __future__ import annotations

import pytest

from ansiq.execution.executor import ExecutionResult, LocalExecutor


class TestLocalExecutor:
    @pytest.mark.asyncio
    async def test_python_execution(self):
        """Test executing Python code locally."""
        executor = LocalExecutor()
        result = await executor.execute("print('hello')")
        assert isinstance(result, ExecutionResult)

    @pytest.mark.asyncio
    async def test_python_execution_with_result(self):
        """Test Python code that produces output."""
        executor = LocalExecutor()
        result = await executor.execute("print(2 + 2)")
        assert isinstance(result, ExecutionResult)

    @pytest.mark.asyncio
    async def test_python_execution_error(self):
        """Test Python code that raises an error."""
        executor = LocalExecutor()
        result = await executor.execute("1/0")
        assert isinstance(result, ExecutionResult)

    @pytest.mark.asyncio
    async def test_shell_command(self):
        """Test executing a shell command."""
        executor = LocalExecutor()
        result = await executor.execute_command("echo test_shell")
        assert isinstance(result, ExecutionResult)

    @pytest.mark.asyncio
    async def test_bash_as_python(self):
        """Test executing bash via execute() with language='bash'."""
        executor = LocalExecutor()
        result = await executor.execute("echo bash_exec", language="bash")
        assert isinstance(result, ExecutionResult)

    @pytest.mark.asyncio
    async def test_execute_invalid_language(self):
        """Test executing with unsupported language."""
        executor = LocalExecutor()
        result = await executor.execute("code", language="brainfuck")
        assert isinstance(result, ExecutionResult)
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_shell_timeout(self):
        """Test shell command that times out."""
        executor = LocalExecutor()
        result = await executor.execute_command("sleep 1")
        assert isinstance(result, ExecutionResult)

    @pytest.mark.asyncio
    async def test_write_file(self, tmp_path):
        """Test writing a file."""
        executor = LocalExecutor()
        test_file = tmp_path / "test_write.txt"
        success = await executor.write_file(str(test_file), "test content")
        assert success
        assert test_file.read_text() == "test content"

    @pytest.mark.asyncio
    async def test_read_file(self, tmp_path):
        """Test reading a file."""
        executor = LocalExecutor()
        test_file = tmp_path / "test_read.txt"
        test_file.write_text("read me")

        content = await executor.read_file(str(test_file))
        assert content == "read me"

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self):
        """Test reading a non-existent file."""
        executor = LocalExecutor()
        content = await executor.read_file("/nonexistent/file.txt")
        assert content is None

    def test_execution_result(self):
        """Test ExecutionResult model."""
        result = ExecutionResult(success=True, output="done", exit_code=0)
        assert result.success
        assert result.output == "done"

    def test_execution_result_error(self):
        """Test ExecutionResult with error."""
        result = ExecutionResult(success=False, error="Failed", exit_code=1)
        assert not result.success
        assert result.error == "Failed"
        assert result.exit_code == 1

    def test_execution_result_repr(self):
        """Test ExecutionResult string representation."""
        result = ExecutionResult(success=True, exit_code=0)
        rep = repr(result)
        assert "ExecutionResult" in rep
        assert "success=True" in rep


class TestExecutionResult:
    def test_default_values(self):
        """Test ExecutionResult default values."""
        result = ExecutionResult(success=True)
        assert result.output == ""
        assert result.error is None
        assert result.exit_code == 0
