"""MCPClientTool — wraps a single MCP tool as a Nova BaseTool.

The agent/LLM sees MCP tools identically to native tools.
One instance per remote tool, namespaced as 'server__tool_name'.
"""

import logging
from typing import Any, Dict, Optional

from src.core.tools.base import BaseTool
from src.core.types import ToolResult

logger = logging.getLogger(__name__)


class MCPClientTool(BaseTool):
    """Adapter: bridges one MCP tool into Nova's BaseTool interface."""

    def __init__(
        self,
        server_name: str,
        mcp_tool_name: str,
        description: str,
        input_schema: Dict[str, Any],
        session_provider,  # async callable → ClientSession or None
    ):
        # Namespaced to avoid collisions: "weather__get_forecast"
        self.name = f"{server_name}__{mcp_tool_name}"
        self.description = f"[MCP:{server_name}] {description}"
        self._mcp_tool_name = mcp_tool_name
        self._server_name = server_name
        self._session_provider = session_provider

        # BaseTool.parameters used by default to_anthropic_tool()
        self.parameters = input_schema.get("properties", {})
        # Keep full schema for override (preserves 'required' subset)
        self._input_schema = input_schema

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Override: pass full MCP JSON Schema as input_schema.

        MCP tools may have 'required' as a subset of properties,
        unlike native tools where required = all keys.
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._input_schema,
        }

    def validate_params(self, **kwargs) -> bool:
        """Validate only the required params from the MCP schema."""
        required = self._input_schema.get("required", [])
        return all(p in kwargs for p in required)

    async def execute(self, **kwargs) -> ToolResult:
        """Call the remote MCP tool via the session provider."""
        try:
            session = await self._session_provider()
            if session is None:
                return ToolResult(
                    success=False,
                    error=f"MCP server '{self._server_name}' is not connected",
                )

            result = await session.call_tool(
                name=self._mcp_tool_name,
                arguments=kwargs,
            )

            # Extract text from content blocks
            text_parts = []
            content_blocks = []
            for block in (result.content or []):
                block_type = getattr(block, "type", "text")
                block_text = getattr(block, "text", str(block))
                if hasattr(block, "text"):
                    text_parts.append(block.text)
                content_blocks.append({"type": block_type, "text": block_text})

            combined_text = "\n".join(text_parts) if text_parts else None

            if result.isError:
                return ToolResult(
                    success=False,
                    error=combined_text or "MCP tool returned error",
                    metadata={"mcp_server": self._server_name},
                )

            return ToolResult(
                success=True,
                output=combined_text,
                content_blocks=content_blocks if content_blocks else None,
                metadata={"mcp_server": self._server_name},
            )

        except Exception as e:
            logger.error(f"MCP tool {self.name} execution failed: {e}")
            return ToolResult(
                success=False,
                error=f"MCP tool error: {e}",
                metadata={"mcp_server": self._server_name},
            )
