"""Clock tool — gives the agent access to current time in user's timezone."""

import logging
from .base import BaseTool
from ..types import ToolResult
from ..timezone import now, format_time, USER_TZ

logger = logging.getLogger(__name__)


class ClockTool(BaseTool):
    """Simple clock tool — returns current date/time in user's timezone (PST)."""

    name = "clock"
    description = "Get the current date and time. Always returns time in user's timezone (US/Pacific). Use this before setting reminders or discussing times."

    parameters = {
        "format": {
            "type": "string",
            "description": "Optional. 'short' for just time, 'date' for just date, or 'full' (default) for both.",
            "enum": ["short", "date", "full"],
            "default": "full"
        }
    }

    async def execute(self, format: str = "full", **kwargs) -> ToolResult:
        """Return current time in user's timezone."""
        current = now()

        if format == "short":
            result = current.strftime("%I:%M %p %Z")
        elif format == "date":
            result = current.strftime("%A, %B %d, %Y")
        else:
            result = (
                f"{current.strftime('%A, %B %d, %Y at %I:%M %p %Z')}\n"
                f"ISO: {current.isoformat()}\n"
                f"Timezone: {USER_TZ}"
            )

        return ToolResult(
            success=True,
            output=result
        )
