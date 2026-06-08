"""Tests for the tool system — BaseTool, ToolRegistry, built-in tools."""

from __future__ import annotations

import pytest

from ansiq.tools.base import BaseTool, ToolParameter, ToolResult
from ansiq.tools.registry import ToolRegistry


class TestBaseTool:
    def test_default_name(self):
        """Test tool gets default name from class."""

        class MyTool(BaseTool):
            description = "My custom tool"

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="done")

        tool = MyTool()
        assert tool.name == "mytool"

    def test_custom_name(self):
        """Test tool with custom name."""

        class NamedTool(BaseTool):
            name = "custom_tool"
            description = "A tool with a custom name"

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="done")

        tool = NamedTool()
        assert tool.name == "custom_tool"

    def test_get_description_without_params(self):
        """Test get_description when no params defined."""

        class SimpleTool(BaseTool):
            name = "simple"
            description = "Just a simple tool"

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="done")

        tool = SimpleTool()
        desc = tool.get_description()
        assert "Just a simple tool" in desc
        assert "Parameters" not in desc

    def test_get_description_with_params(self):
        """Test get_description includes parameter details."""

        class ParamTool(BaseTool):
            name = "param_tool"
            description = "Tool with params"
            parameters = [
                ToolParameter(name="query", type="string", description="The search query"),
                ToolParameter(name="limit", type="integer", description="Max results", required=False),
            ]

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="done")

        tool = ParamTool()
        desc = tool.get_description()
        assert "query" in desc
        assert "string" in desc
        assert "limit" in desc

    def test_to_function_schema(self):
        """Test converting tool to OpenAI function schema."""

        class SchemaTool(BaseTool):
            name = "search"
            description = "Search the web"
            parameters = [
                ToolParameter(name="q", type="string", description="Query"),
            ]

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="done")

        tool = SchemaTool()
        schema = tool.to_function_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "search"
        assert "parameters" in schema["function"]

    def test_execute(self):
        """Test tool execution."""

        class EchoTool(BaseTool):
            name = "echo"
            description = "Echoes input"

            async def execute(self, message: str = "") -> ToolResult:
                return ToolResult(output=message)

        import asyncio

        tool = EchoTool()
        result = asyncio.run(tool.execute(message="Hello"))
        assert result.output == "Hello"
        assert result.success

    def test_run_convenience(self):
        """Test run convenience method."""

        class TestTool(BaseTool):
            name = "test"
            description = "Test"

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult(output="convenience")

        import asyncio

        tool = TestTool()
        output = asyncio.run(tool.run())
        assert output == "convenience"


class TestToolRegistry:
    def setup_method(self):
        ToolRegistry._tools.clear()

    def test_register_and_get(self):
        """Test registering and getting a tool."""

        class T1(BaseTool):
            name = "tool_one"
            description = "First tool"
            async def execute(self, **kwargs): return ToolResult()

        tool = T1()
        ToolRegistry.register(tool)
        assert ToolRegistry.get("tool_one") is not None

    def test_register_class(self):
        """Test registering a tool class."""

        class T2(BaseTool):
            name = "tool_two"
            description = "Second tool"
            async def execute(self, **kwargs): return ToolResult()

        ToolRegistry.register_class(T2)
        assert ToolRegistry.get("tool_two") is not None

    def test_unregister(self):
        """Test unregistering a tool."""

        class T3(BaseTool):
            name = "temp_tool"
            description = "Will be removed"
            async def execute(self, **kwargs): return ToolResult()

        ToolRegistry.register_class(T3)
        ToolRegistry.unregister("temp_tool")
        assert ToolRegistry.get("temp_tool") is None

    def test_list_tools(self):
        """Test listing all tools."""

        class T4(BaseTool):
            name = "tool_a"
            description = "A"
            async def execute(self, **kwargs): return ToolResult()

        class T5(BaseTool):
            name = "tool_b"
            description = "B"
            async def execute(self, **kwargs): return ToolResult()

        ToolRegistry.register_class(T4)
        ToolRegistry.register_class(T5)
        assert len(ToolRegistry.list_tools()) == 2

    def test_get_schemas(self):
        """Test getting all tool schemas."""

        class T6(BaseTool):
            name = "schema_tool"
            description = "For schema"
            async def execute(self, **kwargs): return ToolResult()

        ToolRegistry.register_class(T6)
        schemas = ToolRegistry.get_schemas()
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "schema_tool"


class TestToolParameter:
    def test_default_values(self):
        """Test ToolParameter default values."""
        param = ToolParameter(name="query", type="string")
        assert param.description == ""
        assert param.required is True


class TestBuiltinTools:
    """Integration tests for built-in tools."""

    @pytest.mark.asyncio
    async def test_list_directory(self, tmp_path):
        """Test listing a directory."""
        from ansiq.tools.builtin import ListDirectoryTool

        # Create some test files
        (tmp_path / "file1.txt").write_text("hello")
        (tmp_path / "file2.txt").write_text("world")
        (tmp_path / "subdir").mkdir()

        tool = ListDirectoryTool()
        result = await tool.execute(path=str(tmp_path))
        assert result.success
        assert "file1.txt" in result.output
        assert "subdir" in result.output

    @pytest.mark.asyncio
    async def test_list_nonexistent_directory(self):
        """Test listing a non-existent directory."""
        from ansiq.tools.builtin import ListDirectoryTool

        tool = ListDirectoryTool()
        result = await tool.execute(path="/nonexistent/path/xyz")
        assert not result.success

    @pytest.mark.asyncio
    async def test_write_and_read_file(self, tmp_path):
        """Test writing and reading a file."""
        from ansiq.tools.builtin import ReadFileTool, WriteFileTool

        file_path = tmp_path / "test_output.txt"

        write_tool = WriteFileTool()
        result = await write_tool.execute(
            path=str(file_path),
            content="Hello, World!",
        )
        assert result.success

        read_tool = ReadFileTool()
        result = await read_tool.execute(path=str(file_path))
        assert result.success
        assert "Hello, World!" in result.output

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self):
        """Test reading a non-existent file."""
        from ansiq.tools.builtin import ReadFileTool

        tool = ReadFileTool()
        result = await tool.execute(path="/nonexistent/file.txt")
        assert not result.success

    @pytest.mark.asyncio
    async def test_python_execute(self):
        """Test executing Python code."""
        from ansiq.tools.builtin import PythonExecuteTool

        tool = PythonExecuteTool()
        result = await tool.execute(code="print('hello from test')")
        assert result.success
        assert "hello from test" in result.output

    @pytest.mark.asyncio
    async def test_python_execute_error(self):
        """Test Python execution error handling."""
        from ansiq.tools.builtin import PythonExecuteTool

        tool = PythonExecuteTool()
        result = await tool.execute(code="raise ValueError('test error')")
        assert not result.success
        assert "ValueError" in result.output or "test error" in result.output

    @pytest.mark.asyncio
    async def test_shell_command(self):
        """Test shell command execution."""
        from ansiq.tools.builtin import ShellCommandTool

        tool = ShellCommandTool()
        result = await tool.execute(command="echo hello from shell")
        assert result.success
        assert "hello from shell" in result.output

    @pytest.mark.asyncio
    async def test_web_search(self):
        """Test web search tool (may fail without internet)."""
        from ansiq.tools.builtin import WebSearchTool

        tool = WebSearchTool()
        result = await tool.execute(query="test query")
        # Should not raise even if search fails
        assert result is not None

    @pytest.mark.asyncio
    async def test_web_fetch(self):
        """Test web fetch tool (may fail without internet)."""
        from ansiq.tools.builtin import WebFetchTool

        tool = WebFetchTool()
        result = await tool.execute(url="https://example.com")
        # Should not crash
        assert result is not None

    @pytest.mark.asyncio
    async def test_shell_no_command(self):
        """Test shell with no command."""
        from ansiq.tools.builtin import ShellCommandTool

        tool = ShellCommandTool()
        result = await tool.execute(command="")
        assert not result.success

    @pytest.mark.asyncio
    async def test_python_no_code(self):
        """Test Python execute with no code."""
        from ansiq.tools.builtin import PythonExecuteTool

        tool = PythonExecuteTool()
        result = await tool.execute(code="")
        assert not result.success
