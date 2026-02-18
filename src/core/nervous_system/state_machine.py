"""Agent State Machine — tracks execution state and enables cancellation.

Architecture: Nervous System component.
Allows the Heart to know what the agent is doing at any moment,
and enables user-initiated cancellation of in-progress tasks.
"""

import asyncio
import logging
from enum import Enum
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent execution states."""
    IDLE = "idle"                          # Waiting for input
    PARSING_INTENT = "parsing_intent"      # Classifying user message
    THINKING = "thinking"                  # LLM generating response/plan
    EXECUTING = "executing"                # Running tool calls
    REFLECTING = "reflecting"              # Post-action evaluation
    RESPONDING = "responding"              # Sending response to user
    AWAITING_APPROVAL = "awaiting_approval"  # Waiting for user to approve action


class AgentStateMachine:
    """Tracks agent state and provides cancellation mechanism.

    Usage:
        sm = AgentStateMachine()
        sm.transition(AgentState.THINKING)
        ...
        if sm.is_cancelled():
            return  # User cancelled
        sm.transition(AgentState.EXECUTING)
    """

    def __init__(self):
        self._state = AgentState.IDLE
        self._cancel_event = asyncio.Event()
        self._state_changed_at = datetime.now()
        self._current_task_description = ""

    @property
    def state(self) -> AgentState:
        return self._state

    def transition(self, new_state: AgentState, task_description: str = ""):
        """Transition to a new state.

        Args:
            new_state: Target state
            task_description: What the agent is doing (for status display)
        """
        old_state = self._state
        self._state = new_state
        self._state_changed_at = datetime.now()
        if task_description:
            self._current_task_description = task_description

        logger.debug(f"State: {old_state.value} → {new_state.value}")

    def request_cancel(self):
        """Request cancellation of current operation (called by Heart when user says 'cancel')."""
        if self._state not in (AgentState.IDLE, AgentState.RESPONDING):
            logger.info(f"Cancellation requested (current state: {self._state.value})")
            self._cancel_event.set()

    def is_cancelled(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancel_event.is_set()

    def reset(self):
        """Reset to IDLE state and clear cancellation."""
        self._state = AgentState.IDLE
        self._cancel_event.clear()
        self._current_task_description = ""
        self._state_changed_at = datetime.now()

    def get_status(self) -> dict:
        """Get current state info (for dashboard/status command)."""
        return {
            "state": self._state.value,
            "task": self._current_task_description,
            "since": self._state_changed_at.isoformat(),
            "cancelled": self._cancel_event.is_set()
        }
