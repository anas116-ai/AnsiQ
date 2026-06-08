"""File operation tools — read, write, list files."""

from __future__ import annotations

import logging
from pathlib import Path

import aiofiles

from ansiq.tools.base import BaseTool, ToolParameter, ToolResult

logger = logging.getLogger(__name__)


class ReadFileTool(BaseTool):
    """Read the contents of a file."""

    name = "read_file"
    description = "Read the contents of a file at the specified path"
    parameters = [
        ToolParameter(name="path", type="string", description="Path to the file to read"),
    ]

    async def execute(self, path: str = "") -> ToolResult:
        try:
            resolved = Path(path).expanduser().resolve()
            if not resolved.exists():
                return ToolResult(
                    success=False, output=f"File not found: {path}", error="File not found"
                )
            async with aiofiles.open(resolved) as f:
                text = await f.read()
            return ToolResult(output=text, data={"path": str(resolved), "size": len(text)})
        except Exception as e:
            return ToolResult(success=False, output=str(e), error=str(e))


class WriteFileTool(BaseTool):
    """Write content to a file."""

    name = "write_file"
    description = "Write content to a file at the specified path"
    parameters = [
        ToolParameter(name="path", type="string", description="Path to write to"),
        ToolParameter(name="content", type="string", description="Content to write"),
    ]

    async def execute(self, path: str = "", content: str = "") -> ToolResult:
        try:
            resolved = Path(path).expanduser().resolve()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(resolved, "w") as f:
                await f.write(content)
            return ToolResult(output=f"Written {len(content)} bytes to {resolved}")
        except Exception as e:
            return ToolResult(success=False, output=str(e), error=str(e))


class ListDirectoryTool(BaseTool):
    """List files and directories in a path."""

    name = "list_directory"
    description = "List all files and directories in the specified path"
    parameters = [
        ToolParameter(name="path", type="string", description="Directory path to list"),
    ]

    async def execute(self, path: str = ".") -> ToolResult:
        try:
            resolved = Path(path).expanduser().resolve()
            if not resolved.exists():
                return ToolResult(success=False, output=f"Directory not found: {path}")
            if not resolved.is_dir():
                return ToolResult(success=False, output=f"Not a directory: {path}")

            files = []
            dirs = []
            for entry in resolved.iterdir():
                if entry.is_dir():
                    dirs.append(entry.name + "/")
                else:
                    files.append(entry.name)

            output = f"Directory: {resolved}\n"
            output += f"\nDirectories ({len(dirs)}):\n" + "\n".join(sorted(dirs)) if dirs else ""
            output += f"\nFiles ({len(files)}):\n" + "\n".join(sorted(files)) if files else ""

            return ToolResult(output=output, data={"files": files, "directories": dirs})
        except Exception as e:
            return ToolResult(success=False, output=str(e), error=str(e))
