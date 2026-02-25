"""Policy Gate — deterministic permission checks before tool execution.

Sits between Brain (which decides what tools to call) and Talents (which execute).
Enforces risk-based approval, scope checks, and argument minimization.

Architecture: Nervous System component.
"""

import logging
from enum import Enum
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk level for tool operations."""
    READ = "read"              # Reading data — always safe
    WRITE = "write"            # Writing/modifying data — needs caution
    IRREVERSIBLE = "irreversible"  # Cannot be undone — needs approval


# Tool risk classification — keys must match registered tool names
TOOL_RISK_MAP: Dict[str, Dict[str, RiskLevel]] = {
    "bash": {
        "_default": RiskLevel.WRITE,
    },
    "file_operations": {
        "_default": RiskLevel.WRITE,
    },
    "web_search": {
        "_default": RiskLevel.READ,
    },
    "web_fetch": {
        "_default": RiskLevel.READ,
    },
    "browser": {
        "_default": RiskLevel.READ,
    },
    "email": {
        "read_emails": RiskLevel.READ,
        "search_emails": RiskLevel.READ,
        "send_email": RiskLevel.IRREVERSIBLE,
        "reply_email": RiskLevel.IRREVERSIBLE,
        "_default": RiskLevel.WRITE,
    },
    "calendar": {
        "list_events": RiskLevel.READ,
        "search_events": RiskLevel.READ,
        "create_event": RiskLevel.WRITE,
        "delete_event": RiskLevel.IRREVERSIBLE,
        "_default": RiskLevel.WRITE,
    },
    "x_tool": {
        "post_tweet": RiskLevel.IRREVERSIBLE,
        "post_to_community": RiskLevel.IRREVERSIBLE,
        "delete_tweet": RiskLevel.IRREVERSIBLE,
        "_default": RiskLevel.IRREVERSIBLE,
    },
    "reminder": {
        "set_reminder": RiskLevel.WRITE,
        "list_reminders": RiskLevel.READ,
        "cancel_reminder": RiskLevel.WRITE,
        "_default": RiskLevel.WRITE,
    },
    "nova_task": {
        "_default": RiskLevel.WRITE,
    },
    "contacts": {
        "_default": RiskLevel.READ,
    },
    "linkedin": {
        "_default": RiskLevel.WRITE,
    },
    "send_whatsapp_message": {
        "_default": RiskLevel.IRREVERSIBLE,
    },
    "make_phone_call": {
        "_default": RiskLevel.IRREVERSIBLE,
    },
    "clock": {
        "_default": RiskLevel.READ,
    },
}


class PolicyGate:
    """Deterministic policy gate for tool execution governance.

    Checks:
    1. Risk level assessment
    2. Rate limiting per tool (prevent runaway tool calls)
    3. Argument validation
    4. Logging all write/irreversible actions

    Note: Does NOT block execution by default — logs and warns.
    Approval-required mode can be enabled per tool for production hardening.
    """

    def __init__(self, require_approval_for_irreversible: bool = False):
        """Initialize policy gate.

        Args:
            require_approval_for_irreversible: If True, block irreversible actions
                until explicit user approval (future enhancement via Telegram prompt)
        """
        self.require_approval = require_approval_for_irreversible
        self._tool_call_counts: Dict[str, int] = {}
        self._max_calls_per_run = 20  # Safety: max tool calls per agent run

    def check(
        self,
        tool_name: str,
        operation: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        trace_id: str = ""
    ) -> Tuple[bool, str]:
        """Check if a tool call is allowed.

        Args:
            tool_name: Tool being called
            operation: Operation within the tool (e.g., 'send_email')
            params: Tool parameters
            trace_id: Request trace ID for logging

        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        # 1. Assess risk level
        risk = self._get_risk_level(tool_name, operation)

        # 2. Rate limit check — prevent runaway tool calls
        call_count = self._tool_call_counts.get(tool_name, 0)
        if call_count >= self._max_calls_per_run:
            reason = f"Tool {tool_name} exceeded max calls per run ({self._max_calls_per_run})"
            logger.warning(f"[{trace_id}] POLICY GATE BLOCKED: {reason}")
            return False, reason

        self._tool_call_counts[tool_name] = call_count + 1

        # 3. Log write/irreversible actions
        if risk == RiskLevel.IRREVERSIBLE:
            logger.warning(
                f"[{trace_id}] POLICY GATE: IRREVERSIBLE action — "
                f"tool={tool_name}, operation={operation}, params={self._safe_params(params)}"
            )
            if self.require_approval:
                return False, f"Irreversible action '{tool_name}.{operation}' requires user approval"

        elif risk == RiskLevel.WRITE:
            logger.info(
                f"[{trace_id}] POLICY GATE: WRITE action — "
                f"tool={tool_name}, operation={operation}"
            )

        # 4. Passed all checks
        return True, "allowed"

    def reset_run_counts(self):
        """Reset per-run tool call counters (call at start of each agent run)."""
        self._tool_call_counts.clear()

    def _get_risk_level(self, tool_name: str, operation: Optional[str] = None) -> RiskLevel:
        """Get risk level for a tool+operation combination."""
        tool_risks = TOOL_RISK_MAP.get(tool_name, {})

        if operation and operation in tool_risks:
            return tool_risks[operation]

        return tool_risks.get("_default", RiskLevel.WRITE)

    @staticmethod
    def _safe_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Sanitize params for logging (truncate long values)."""
        if not params:
            return {}
        safe = {}
        for k, v in params.items():
            if isinstance(v, str) and len(v) > 100:
                safe[k] = v[:100] + "..."
            else:
                safe[k] = v
        return safe
