"""Base tool interface for all agent tools."""

from abc import ABC, abstractmethod
from typing import Dict, Any
from ..types import ToolResult


class BaseTool(ABC):
    """Abstract base class for all tools available to the agent."""

    name: str
    description: str
    parameters: Dict[str, Any]

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given parameters.

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            ToolResult with success status and output/error
        """
        pass

    def to_anthropic_tool(self) -> Dict[str, Any]:
        """Convert tool to Anthropic API format.

        Returns:
            Tool definition dict for Claude API
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": list(self.parameters.keys())
            }
        }

    def validate_params(self, **kwargs) -> bool:
        """Validate that required parameters are provided.

        Args:
            **kwargs: Parameters to validate

        Returns:
            True if valid, False otherwise
        """
        for param_name in self.parameters.keys():
            if param_name not in kwargs:
                return False
        return True
