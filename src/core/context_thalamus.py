"""Context Thalamus — active token budgeting and context window management.

Architecture: Heart component.
Prevents prompt bloat by enforcing token budgets per section
and summarizing long conversation histories before sending to the Brain.
"""

import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class ContextThalamus:
    """Manages context window allocation and prevents token bloat.

    Token budgets (approximate, using ~4 chars per token):
    - System prompt (static): ~500 tokens
    - Intelligence principles: ~300 tokens
    - Security rules: ~100 tokens
    - Brain context (memories): ~400 tokens
    - Conversation history: ~2000 tokens
    - Tool definitions: ~800 tokens
    - Current message: unlimited
    Total target: ~4100 tokens of context (well within Claude's window)
    """

    # Token budgets per section (in characters, ~4 chars per token)
    BUDGET_BRAIN_CONTEXT = 1600      # ~400 tokens
    BUDGET_HISTORY = 8000            # ~2000 tokens
    BUDGET_PRINCIPLES = 1200         # ~300 tokens

    # Conversation history management
    MAX_HISTORY_TURNS = 20           # Keep last N turns in active session
    SUMMARIZE_AFTER_TURNS = 15      # Summarize older turns after this many

    def __init__(self):
        """Initialize the context thalamus."""
        self._conversation_histories: Dict[str, List[Dict[str, str]]] = {}

    def budget_brain_context(self, context: str) -> str:
        """Enforce token budget on brain context.

        Args:
            context: Raw brain context string

        Returns:
            Trimmed context within budget
        """
        if len(context) <= self.BUDGET_BRAIN_CONTEXT:
            return context

        # Truncate with indicator
        truncated = context[:self.BUDGET_BRAIN_CONTEXT - 20]
        # Cut at last complete line
        last_newline = truncated.rfind('\n')
        if last_newline > 0:
            truncated = truncated[:last_newline]

        return truncated + "\n[...truncated]"

    def budget_principles(self, principles: str) -> str:
        """Enforce token budget on intelligence principles.

        Args:
            principles: Raw principles string

        Returns:
            Trimmed principles within budget
        """
        if len(principles) <= self.BUDGET_PRINCIPLES:
            return principles

        return principles[:self.BUDGET_PRINCIPLES - 20] + "\n[...truncated]"

    def manage_history(
        self,
        session_id: str,
        new_user_msg: str,
        new_bot_msg: str
    ) -> List[Dict[str, str]]:
        """Add a turn and return managed conversation history.

        Keeps recent turns and summarizes older ones to stay within budget.

        Args:
            session_id: User/session identifier
            new_user_msg: New user message to add
            new_bot_msg: New bot response to add

        Returns:
            Managed conversation history within budget
        """
        if session_id not in self._conversation_histories:
            self._conversation_histories[session_id] = []

        history = self._conversation_histories[session_id]

        # Add new turn
        history.append({
            "role": "user",
            "content": new_user_msg
        })
        history.append({
            "role": "assistant",
            "content": new_bot_msg
        })

        # Prune if too many turns (keep last MAX_HISTORY_TURNS * 2 messages)
        max_messages = self.MAX_HISTORY_TURNS * 2
        if len(history) > max_messages:
            # Keep summary of old turns + recent turns
            old_turns = history[:len(history) - max_messages]
            recent_turns = history[len(history) - max_messages:]

            # Create a simple summary of old turns
            summary = self._summarize_turns(old_turns)

            # Replace history with summary + recent
            self._conversation_histories[session_id] = [
                {"role": "user", "content": f"[Previous conversation summary: {summary}]"},
            ] + recent_turns

        return self._conversation_histories[session_id]

    def get_history(self, session_id: str) -> List[Dict[str, str]]:
        """Get current conversation history for a session."""
        return self._conversation_histories.get(session_id, [])

    def clear_history(self, session_id: str):
        """Clear conversation history for a session."""
        self._conversation_histories.pop(session_id, None)

    def _summarize_turns(self, turns: List[Dict[str, str]]) -> str:
        """Create a simple summary of conversation turns.

        This is a basic extractive summary. For production, this could
        call Haiku to generate a proper abstractive summary.

        Args:
            turns: Old conversation turns to summarize

        Returns:
            Brief summary string
        """
        topics = []
        for turn in turns:
            content = turn.get("content", "")
            if turn["role"] == "user" and len(content) > 10:
                # Take first 50 chars of each user message as topic hint
                topics.append(content[:50].strip())

        if not topics:
            return "Earlier conversation about various topics."

        # Keep up to 5 topic hints
        topic_hints = "; ".join(topics[:5])
        return f"Discussed: {topic_hints}"

    def get_stats(self) -> Dict[str, Any]:
        """Get thalamus statistics."""
        return {
            "active_sessions": len(self._conversation_histories),
            "total_messages": sum(
                len(h) for h in self._conversation_histories.values()
            )
        }
