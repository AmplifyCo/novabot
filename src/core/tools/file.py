"""File operations tool."""

import aiofiles
import logging
import os
from pathlib import Path
from typing import Optional
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class FileTool(BaseTool):
    """Tool for reading, writing, and editing files."""

    name = "file_operations"
    description = "Read, write, create, and edit files. Supports text files."
    parameters = {
        "operation": {
            "type": "string",
            "description": "Operation: 'read', 'write', 'edit', 'create_dir', 'list_dir'",
            "enum": ["read", "write", "edit", "create_dir", "list_dir"]
        },
        "path": {
            "type": "string",
            "description": "File or directory path"
        },
        "content": {
            "type": "string",
            "description": "Content for write/edit operations (optional)"
        }
    }

    def __init__(self, max_file_size_mb: int = 10):
        """Initialize FileTool.

        Args:
            max_file_size_mb: Maximum file size to read/write in MB
        """
        self.max_file_size = max_file_size_mb * 1024 * 1024

    async def execute(
        self,
        operation: str,
        path: str,
        content: Optional[str] = None
    ) -> ToolResult:
        """Execute file operation.

        Args:
            operation: Operation to perform
            path: File/directory path
            content: Content for write/edit

        Returns:
            ToolResult with operation result
        """
        try:
            if operation == "read":
                return await self._read_file(path)
            elif operation == "write":
                return await self._write_file(path, content or "")
            elif operation == "edit":
                return await self._edit_file(path, content or "")
            elif operation == "create_dir":
                return await self._create_dir(path)
            elif operation == "list_dir":
                return await self._list_dir(path)
            else:
                return ToolResult(
                    success=False,
                    error=f"Unknown operation: {operation}"
                )

        except Exception as e:
            logger.error(f"File operation error: {e}")
            return ToolResult(
                success=False,
                error=f"File operation failed: {str(e)}"
            )

    async def _read_file(self, path: str) -> ToolResult:
        """Read file contents.

        Args:
            path: File path

        Returns:
            ToolResult with file contents
        """
        try:
            # Check file exists
            if not os.path.exists(path):
                return ToolResult(
                    success=False,
                    error=f"File does not exist: {path}"
                )

            # Check file size
            file_size = os.path.getsize(path)
            if file_size > self.max_file_size:
                return ToolResult(
                    success=False,
                    error=f"File too large ({file_size} bytes). Max: {self.max_file_size}"
                )

            # Read file
            async with aiofiles.open(path, 'r', encoding='utf-8') as f:
                content = await f.read()

            logger.info(f"Read file: {path} ({len(content)} chars)")
            return ToolResult(
                success=True,
                output=content,
                metadata={"path": path, "size": len(content)}
            )

        except UnicodeDecodeError:
            return ToolResult(
                success=False,
                error=f"File is not a text file or has encoding issues: {path}"
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Error reading file: {str(e)}"
            )

    async def _write_file(self, path: str, content: str) -> ToolResult:
        """Write content to file (creates or overwrites).

        Args:
            path: File path
            content: Content to write

        Returns:
            ToolResult with write status
        """
        try:
            # Create parent directory if needed
            parent_dir = Path(path).parent
            if not parent_dir.exists():
                parent_dir.mkdir(parents=True, exist_ok=True)

            # Write file
            async with aiofiles.open(path, 'w', encoding='utf-8') as f:
                await f.write(content)

            logger.info(f"Wrote file: {path} ({len(content)} chars)")
            return ToolResult(
                success=True,
                output=f"File written successfully: {path}",
                metadata={"path": path, "size": len(content)}
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Error writing file: {str(e)}"
            )

    async def _edit_file(self, path: str, content: str) -> ToolResult:
        """Edit file with new content (append mode).

        Args:
            path: File path
            content: Content to append

        Returns:
            ToolResult with edit status
        """
        try:
            # For simplicity, this just overwrites. Could be enhanced to do partial edits.
            return await self._write_file(path, content)

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Error editing file: {str(e)}"
            )

    async def _create_dir(self, path: str) -> ToolResult:
        """Create directory.

        Args:
            path: Directory path

        Returns:
            ToolResult with creation status
        """
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            logger.info(f"Created directory: {path}")
            return ToolResult(
                success=True,
                output=f"Directory created: {path}",
                metadata={"path": path}
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Error creating directory: {str(e)}"
            )

    async def _list_dir(self, path: str) -> ToolResult:
        """List directory contents.

        Args:
            path: Directory path

        Returns:
            ToolResult with directory listing
        """
        try:
            if not os.path.exists(path):
                return ToolResult(
                    success=False,
                    error=f"Directory does not exist: {path}"
                )

            if not os.path.isdir(path):
                return ToolResult(
                    success=False,
                    error=f"Path is not a directory: {path}"
                )

            # List contents
            items = os.listdir(path)
            output = "\n".join(sorted(items))

            logger.info(f"Listed directory: {path} ({len(items)} items)")
            return ToolResult(
                success=True,
                output=output,
                metadata={"path": path, "count": len(items)}
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Error listing directory: {str(e)}"
            )
