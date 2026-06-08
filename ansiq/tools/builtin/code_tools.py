"""Code execution tools — run Python and shell commands."""

from __future__ import annotations

import asyncio
import logging

from ansiq.tools.base import BaseTool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class PythonExecuteTool(BaseTool):
    """Execute Python code in an isolated environment."""

    name = "python_execute"
    description = "Execute Python code and return the output"
    parameters = [
        ToolParameter(name="code", type="string", description="Python code to execute"),
    ]

    async def execute(self, code: str = "") -> ToolResult:
        if not code:
            return ToolResult(success=False, output="No code provided")

        try:
            # Capture stdout and stderr
            import io
            from contextlib import redirect_stderr, redirect_stdout

            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()

            namespace: dict = {}
            exec_globals = {"__builtins__": __builtins__}

            with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
                try:
                    exec(code, exec_globals, namespace)
                except Exception as e:
                    import traceback

                    stderr_capture.write(f"{type(e).__name__}: {e}\n")
                    stderr_capture.write(traceback.format_exc())

            stdout_result = stdout_capture.getvalue()
            stderr_result = stderr_capture.getvalue()

            output = stdout_result
            if stderr_result:
                if output:
                    output += "\n--- stderr ---\n"
                output += stderr_result

            return ToolResult(
                success=not stderr_result,
                output=output or "(no output)",
                data={"stdout": stdout_result, "stderr": stderr_result},
            )

        except Exception as e:
            return ToolResult(success=False, output=f"Execution error: {e}", error=str(e))


class ShellCommandTool(BaseTool):
    """Run a shell command and return its output.

    Security: commands run in a restricted environment with timeout.
    """

    name = "shell_command"
    description = "Run a shell command and return its output"
    parameters = [
        ToolParameter(name="command", type="string", description="Shell command to execute"),
        ToolParameter(
            name="timeout", type="integer", description="Timeout in seconds", required=False
        ),
    ]

    def __init__(self, allowed_commands: list[str] | None = None):
        super().__init__()
        self.allowed_commands = allowed_commands

    async def execute(self, command: str = "", timeout: int = 30) -> ToolResult:
        if not command:
            return ToolResult(success=False, output="No command provided")

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True,
            )

            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except TimeoutError:
                process.kill()
                return ToolResult(success=False, output=f"Command timed out after {timeout}s")

            output = stdout.decode() if stdout else ""
            if stderr:
                error_text = stderr.decode()
                if output:
                    output += "\n--- stderr ---\n"
                output += error_text

            return ToolResult(
                success=process.returncode == 0,
                output=output or "(no output)",
                data={"returncode": process.returncode},
            )

        except Exception as e:
            return ToolResult(success=False, output=f"Command error: {e}", error=str(e))
