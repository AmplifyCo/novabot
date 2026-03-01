"""Contact Intelligence — per-contact interaction history tracking.

Tracks when Nova communicated with someone, what about, and flags gaps.
Surfaces "Last time you emailed Sarah..." and "pending follow-ups" in prompts.

Zero LLM calls. Purely structured data in JSON.
"""

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ContactIntelligence:
    """Tracks per-contact interaction history for relationship intelligence."""

    INTERACTIONS_PATH = Path("data/contact_interactions.json")
    MAX_PER_CONTACT = 20

    def __init__(self, path: Optional[str] = None):
        if path:
            self.INTERACTIONS_PATH = Path(path)
        self._interactions: Dict[str, List[Dict]] = self._load()

    # ── Load / Save ────────────────────────────────────────────────────

    def _load(self) -> Dict[str, List[Dict]]:
        if self.INTERACTIONS_PATH.exists():
            try:
                return json.loads(self.INTERACTIONS_PATH.read_text())
            except Exception:
                pass
        return {}

    def _save(self):
        self.INTERACTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self._interactions, indent=2, default=str)
        fd, tmp = tempfile.mkstemp(dir=self.INTERACTIONS_PATH.parent, suffix=".tmp")
        try:
            with open(fd, "w") as f:
                f.write(data)
            Path(tmp).rename(self.INTERACTIONS_PATH)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ── Record ─────────────────────────────────────────────────────────

    def record_interaction(
        self,
        contact_name: str,
        channel: str,
        direction: str = "outbound",
        summary: str = "",
        needs_followup: bool = False,
    ):
        """Record an interaction with a contact.

        Args:
            contact_name: Name of the contact
            channel: Communication channel (email, whatsapp, phone)
            direction: 'outbound' or 'inbound'
            summary: Brief description (max 100 chars)
            needs_followup: Whether this interaction needs follow-up
        """
        key = contact_name.strip().lower()
        if not key:
            return

        if key not in self._interactions:
            self._interactions[key] = []

        self._interactions[key].append({
            "timestamp": datetime.now().isoformat(),
            "channel": channel,
            "direction": direction,
            "summary": summary.strip()[:100],
            "needs_followup": needs_followup,
        })

        # Cap per contact
        if len(self._interactions[key]) > self.MAX_PER_CONTACT:
            self._interactions[key] = self._interactions[key][-self.MAX_PER_CONTACT:]

        self._save()
        logger.info(f"Contact interaction recorded: {contact_name} via {channel}")

    # ── Context retrieval ──────────────────────────────────────────────

    def get_contact_context(self, contact_name: str) -> str:
        """Return formatted interaction history for a specific contact.

        Returns '' if no history exists.
        """
        key = contact_name.strip().lower()
        history = self._interactions.get(key, [])
        if not history:
            return ""

        # Show last 5 interactions
        recent = history[-5:]
        lines = [f"INTERACTION HISTORY — {contact_name}:"]
        for item in recent:
            ts = item.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts)
                date_str = dt.strftime("%b %d")
            except (ValueError, TypeError):
                date_str = "?"
            direction = "→" if item.get("direction") == "outbound" else "←"
            channel = item.get("channel", "?")
            summary = item.get("summary", "")
            followup = " (NEEDS FOLLOW-UP)" if item.get("needs_followup") else ""
            lines.append(f"  [{date_str}] {direction} {channel}: {summary}{followup}")

        return "\n".join(lines)

    def get_followup_context(self) -> str:
        """Return pending follow-ups across all contacts.

        Returns formatted 'PENDING FOLLOW-UPS' section or ''.
        """
        pending = []
        for name, history in self._interactions.items():
            for item in reversed(history):
                if item.get("needs_followup"):
                    ts = item.get("timestamp", "")
                    try:
                        dt = datetime.fromisoformat(ts)
                        date_str = dt.strftime("%b %d")
                    except (ValueError, TypeError):
                        date_str = "?"
                    pending.append({
                        "name": name.title(),
                        "summary": item.get("summary", ""),
                        "date": date_str,
                        "channel": item.get("channel", "?"),
                    })
                    break  # only most recent pending per contact

        if not pending:
            return ""

        lines = ["PENDING FOLLOW-UPS:"]
        for p in pending[:5]:
            lines.append(f"  - {p['name']}: {p['summary']} ({p['channel']}, {p['date']}, no reply yet)")
        return "\n".join(lines)

    def get_stale_contacts(self, days: int = 14) -> List[Dict[str, Any]]:
        """Return contacts with no interaction in N days.

        Used by AttentionEngine for proactive suggestions.
        """
        cutoff = datetime.now().timestamp() - (days * 86400)
        stale = []

        for name, history in self._interactions.items():
            if not history:
                continue
            last = history[-1]
            try:
                last_ts = datetime.fromisoformat(last["timestamp"]).timestamp()
            except (ValueError, KeyError):
                continue
            if last_ts < cutoff:
                try:
                    last_date = datetime.fromisoformat(last["timestamp"]).strftime("%b %d")
                except (ValueError, KeyError):
                    last_date = "?"
                stale.append({
                    "name": name.title(),
                    "last_date": last_date,
                    "channel": last.get("channel", "?"),
                })

        # Sort by staleness (oldest first)
        return stale[:5]
