"""Durable Outbox — prevents double-send of side effects on retry.

Architecture: Nervous System component.

For irreversible actions (email send, X post), we record the intent
BEFORE execution and mark it SENT after. On retry/restart, if an
entry exists as PENDING, we know it was attempted but not confirmed —
skip re-execution.

Uses idempotency keys: hash(tool_name + operation + normalized_args).
"""

import hashlib
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class DurableOutbox:
    """Persistent outbox for side-effect deduplication.

    Lifecycle per side-effect:
    1. Before execution: record(key, PENDING)
    2. After success: mark_sent(key)
    3. On retry: check is_duplicate(key) → skip if already SENT

    Storage: JSON file (data/outbox.json)
    """

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.outbox_file = self.data_dir / "outbox.json"
        # Tools that produce irreversible side effects
        self.SIDE_EFFECT_TOOLS = {"email", "x_post"}

    def is_side_effect_tool(self, tool_name: str) -> bool:
        """Check if this tool has irreversible side effects."""
        return tool_name in self.SIDE_EFFECT_TOOLS

    def make_idempotency_key(
        self,
        tool_name: str,
        operation: str,
        args: Dict[str, Any]
    ) -> str:
        """Generate idempotency key from tool call details."""
        # Normalize: sort keys, strip whitespace
        normalized = json.dumps(
            {"tool": tool_name, "op": operation, "args": args},
            sort_keys=True
        )
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def record_pending(self, key: str, tool_name: str, operation: str, args: Dict[str, Any]):
        """Record a pending side effect (BEFORE execution)."""
        entries = self._load()
        entries[key] = {
            "status": "pending",
            "tool": tool_name,
            "operation": operation,
            "args_summary": {k: str(v)[:100] for k, v in args.items()},
            "recorded_at": datetime.now().isoformat()
        }
        self._save(entries)

    def mark_sent(self, key: str):
        """Mark a side effect as successfully sent."""
        entries = self._load()
        if key in entries:
            entries[key]["status"] = "sent"
            entries[key]["sent_at"] = datetime.now().isoformat()
            self._save(entries)

    def mark_failed(self, key: str, error: str):
        """Mark a side effect as failed."""
        entries = self._load()
        if key in entries:
            entries[key]["status"] = "failed"
            entries[key]["error"] = error
            entries[key]["failed_at"] = datetime.now().isoformat()
            self._save(entries)

    def is_duplicate(self, key: str) -> bool:
        """Check if this side effect was already sent (dedup on retry)."""
        entries = self._load()
        entry = entries.get(key)
        return entry is not None and entry.get("status") == "sent"

    def cleanup_old(self, days: int = 7):
        """Remove outbox entries older than N days."""
        entries = self._load()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cleaned = {
            k: v for k, v in entries.items()
            if v.get("recorded_at", "") > cutoff
        }
        if len(cleaned) < len(entries):
            self._save(cleaned)

    def _load(self) -> Dict[str, Any]:
        if not self.outbox_file.exists():
            return {}
        try:
            with open(self.outbox_file, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def _save(self, entries: Dict[str, Any]):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with open(self.outbox_file, 'w') as f:
            json.dump(entries, f, indent=2, default=str)
