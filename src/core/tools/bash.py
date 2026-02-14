"""Bash command execution tool."""

import asyncio
import logging
from typing import List
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class BashTool(BaseTool):
    """Tool for executing bash commands in a sandboxed environment."""

    name = "bash"
    description = "Execute bash commands safely. Returns stdout, stderr, and return code."
    parameters = {
        "command": {
            "type": "string",
            "description": "The bash command to execute"
        },
        "timeout": {
            "type": "integer",
            "description": "Timeout in seconds (default: 120)",
            "default": 120
        }
    }

    def __init__(self, allowed_commands: List[str] = None, blocked_commands: List[str] = None):
        """Initialize BashTool.

        Args:
            allowed_commands: List of allowed command prefixes (None = all allowed)
            blocked_commands: List of blocked command patterns
        """
        self.allowed_commands = allowed_commands or []
        self.blocked_commands = blocked_commands or [
            "rm -rf /",
            "sudo rm",
            "format",
            "mkfs",
            "dd if=",
        ]

    async def execute(self, command: str, timeout: int = 120) -> ToolResult:
        """Execute a bash command.

        Args:
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            ToolResult with command output
        """
        # Security check
        if self._is_blocked(command):
            logger.warning(f"Blocked dangerous command: {command}")
            return ToolResult(
                success=False,
                error=f"Command blocked for safety: {command}"
            )

        if self.allowed_commands and not self._is_allowed(command):
            logger.warning(f"Command not in allowed list: {command}")
            return ToolResult(
                success=False,
                error=f"Command not allowed: {command}"
            )

        try:
            logger.info(f"Executing bash command: {command}")

            # Create subprocess
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for command to complete with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolResult(
                    success=False,
                    error=f"Command timed out after {timeout} seconds"
                )

            # Decode output
            stdout_str = stdout.decode('utf-8', errors='replace') if stdout else ""
            stderr_str = stderr.decode('utf-8', errors='replace') if stderr else ""

            success = process.returncode == 0

            if success:
                logger.info(f"Command executed successfully")
            else:
                logger.warning(f"Command failed with return code {process.returncode}")

            return ToolResult(
                success=success,
                output=stdout_str,
                error=stderr_str if stderr_str else None,
                metadata={"return_code": process.returncode}
            )

        except Exception as e:
            logger.error(f"Error executing command: {e}")
            return ToolResult(
                success=False,
                error=f"Exception during execution: {str(e)}"
            )

    def _is_blocked(self, command: str) -> bool:
        """Check if command is blocked.

        Args:
            command: Command to check

        Returns:
            True if blocked, False otherwise
        """
        command_lower = command.lower().strip()
        for blocked in self.blocked_commands:
            if blocked.lower() in command_lower:
                return True
        return False

    def _is_allowed(self, command: str) -> bool:
        """Check if command is in allowed list.

        Args:
            command: Command to check

        Returns:
            True if allowed, False otherwise
        """
        if not self.allowed_commands:
            return True  # No restrictions if list is empty

        command_lower = command.lower().strip()
        for allowed in self.allowed_commands:
            if command_lower.startswith(allowed.lower()):
                return True
        return False
