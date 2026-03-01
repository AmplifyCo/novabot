"""Circadian Rhythm — time-of-day behavior modifiers for conversation responses.

Nova adapts its communication style based on the time of day:
- Morning: briefing mode, priorities first
- Work hours: professional, action-oriented (default — no extra modifier)
- Evening: lighter, reflective, offers to defer tasks
- Late night: minimal, concise, no proactive suggestions

Zero LLM calls. Purely rule-based. Zero latency.
"""

import logging

logger = logging.getLogger(__name__)


class CircadianRhythm:
    """Time-based behavior modifiers — static methods, no state."""

    _MODES = {
        "morning_briefing": (6, 10),   # 6am–10am
        "work_hours":       (10, 18),  # 10am–6pm (default, no modifier)
        "evening":          (18, 22),  # 6pm–10pm
        "late_night":       (22, 6),   # 10pm–6am (wraps midnight)
    }

    _MODIFIERS = {
        "morning_briefing": (
            "Morning mode — lead with priorities and pending items. "
            "Be energizing and concise. If no specific task, offer a quick day overview."
        ),
        "work_hours": "",  # default professional mode — no extra modifier
        "evening": (
            "Evening mode — be lighter and more reflective. "
            "For new tasks, ask 'Want me to handle this now or schedule for tomorrow morning?' "
            "Avoid creating urgency."
        ),
        "late_night": (
            "Late night mode — be extra concise. Don't proactively suggest tasks. "
            "Only respond to what's asked. Keep it brief."
        ),
    }

    @classmethod
    def get_context(cls) -> str:
        """Return circadian context for prompt injection.

        Returns formatted section or '' (empty for work hours — default mode).
        """
        try:
            from src.core.timezone import now as tz_now
            hour = tz_now().hour
        except Exception:
            return ""

        mode = cls._resolve_mode(hour)
        modifier = cls._MODIFIERS.get(mode, "")
        if not modifier:
            return ""
        return f"TIME-OF-DAY BEHAVIOR:\n{modifier}"

    @classmethod
    def _resolve_mode(cls, hour: int) -> str:
        """Map hour (0–23) to a circadian mode."""
        for mode, (start, end) in cls._MODES.items():
            if start <= end:
                if start <= hour < end:
                    return mode
            else:
                # Wraps midnight (e.g., late_night: 22–6)
                if hour >= start or hour < end:
                    return mode
        return "work_hours"  # fallback
