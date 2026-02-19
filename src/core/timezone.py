"""Central timezone configuration for the digital twin system.

All user-facing time operations should use `now()` from this module
instead of `datetime.now()` to ensure consistent PST timezone.

The user's default timezone is US/Pacific (PST/PDT).
This can be overridden by setting USER_TIMEZONE env var.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

# Default timezone — can be overridden by env var
_tz_name = os.getenv("USER_TIMEZONE", "America/Los_Angeles")
USER_TZ = ZoneInfo(_tz_name)


def now() -> datetime:
    """Get current time in user's timezone (default: PST)."""
    return datetime.now(USER_TZ)


def format_time(dt: datetime = None) -> str:
    """Format a datetime for user display. Uses PST if no tzinfo."""
    if dt is None:
        dt = now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=USER_TZ)
    return dt.strftime("%Y-%m-%d %H:%M %Z")


def current_time_context() -> str:
    """Return a string describing current time for system prompt injection."""
    t = now()
    return f"Current time: {t.strftime('%Y-%m-%d %H:%M %Z')} ({t.strftime('%A')})"
