"""Skill Tool — learn new API integrations from .md spec files.

Phase 4A: Skill Acquisition.

BaseTool interface that lets the agent invoke SkillLearner via tool calls.
The user says "learn this skill: URL" and this tool handles it.
"""

import logging
from typing import Optional

from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)


class SkillTool(BaseTool):
    """Tool for learning new skills from API spec files."""

    name = "learn_skill"
    description = (
        "Learn a new skill or API integration from a markdown specification file. "
        "Operations: 'learn' (acquire new skill from URL), 'list' (show learned skills), "
        "'status' (check status of a specific skill). "
        "When the user provides an API spec URL or says 'learn this skill', use this tool."
    )
    parameters = {
        "operation": {
            "type": "string",
            "enum": ["learn", "list", "status"],
            "description": (
                "'learn': acquire a new skill from a .md spec URL. "
                "'list': show all learned skills and their status. "
                "'status': check status of a specific skill by name."
            ),
        },
        "url": {
            "type": "string",
            "description": "URL to the .md API spec file. Required for 'learn'.",
        },
        "skill_name": {
            "type": "string",
            "description": "Skill name for 'status' operation.",
        },
    }

    def __init__(self):
        self.skill_learner = None  # Injected by registry.set_skill_learner()
        self._registry = None      # Set by registry for reload passthrough

    def to_anthropic_tool(self):
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": ["operation"],
            },
        }

    async def execute(
        self,
        operation: str = "list",
        url: Optional[str] = None,
        skill_name: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        if not self.skill_learner:
            return ToolResult(
                success=False,
                error="Skill learning system not initialized",
            )

        if operation == "learn":
            if not url or not url.strip():
                return ToolResult(
                    success=False,
                    error="'url' is required for the learn operation. Provide a .md spec URL.",
                )
            # Pass registry for hot-reload
            if self._registry and self.skill_learner.plugin_loader:
                # Monkey-patch _get_registry to return actual registry
                self.skill_learner._get_registry = lambda: self._registry
            success, message = await self.skill_learner.learn_from_url(url.strip())
            return ToolResult(
                success=success,
                output=message if success else None,
                error=message if not success else None,
            )

        elif operation == "list":
            skills = self.skill_learner.get_learned_skills()
            if not skills:
                return ToolResult(
                    success=True,
                    output="No skills learned yet. Send me a .md spec URL to learn a new skill.",
                )
            lines = ["Learned Skills:"]
            for s in skills:
                status_label = {
                    "active": "active",
                    "pending_env": "needs env vars",
                    "reload_failed": "reload failed",
                    "validation_failed": "code validation failed",
                }.get(s.status, s.status)
                lines.append(f"  - {s.name}: {s.description} [{status_label}]")
                if s.status == "pending_env" and s.env_vars_needed:
                    lines.append(f"    Needs: {', '.join(s.env_vars_needed)}")
            return ToolResult(success=True, output="\n".join(lines))

        elif operation == "status":
            if not skill_name:
                return ToolResult(
                    success=False,
                    error="'skill_name' is required for the status operation.",
                )
            meta = self.skill_learner.get_skill_status(skill_name.strip())
            if not meta:
                return ToolResult(
                    success=False,
                    error=f"No skill named '{skill_name}' found.",
                )
            return ToolResult(
                success=True,
                output=(
                    f"Skill: {meta.name}\n"
                    f"Description: {meta.description}\n"
                    f"Source: {meta.source_url}\n"
                    f"Learned: {meta.learned_at}\n"
                    f"Status: {meta.status}\n"
                    f"Env vars: {', '.join(meta.env_vars_needed) or 'none'}"
                ),
            )

        return ToolResult(success=False, error=f"Unknown operation: {operation}")
