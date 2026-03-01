"""Working Memory — persistent session state across conversations.

Humans carry mood, unresolved thoughts, and momentum between conversations.
Nova does the same via this module: tone, unfinished items, and behavioral
calibration instructions persist across restarts.

Security: read/write is local file only. No external calls. No PII stored here
— only tone labels, topic strings (trimmed to 100 chars), and directive text.
"""

import json
import logging
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT = {
    "tone":               "neutral",       # neutral | urgent | stressed | relaxed | formal
    "energy":             "normal",        # low | normal | high
    "unfinished":         [],              # list of brief strings (max 5)
    "calibration":        "",              # user-issued behavioral directive ("be more concise")
    "session_count":      0,
    "last_active":        None,
    "timezone_override":  None,       # {"tz": "America/New_York", "label": "New York", "set_at": "ISO"}
    "open_threads":       [],         # [{"topic": str, "status": str, "updated_at": str}] max 3
    "recent_corrections": [],         # [{"what": str, "when": str}] max 3, auto-expire 24h
    "preference_profile": {},         # {"food": ["Italian"], "style": ["concise"]}
}

_TONES = {
    "urgent":   "⚡ The user is in a hurry — be brief, skip preamble, lead with the answer.",
    "stressed": "🌊 The user seems under pressure — be calm, clear, and reassuring.",
    "relaxed":  "☀️  The user is relaxed — you can be more conversational and thorough.",
    "formal":   "📋 The user is in professional mode — be precise and structured.",
    "neutral":  "",   # no special instruction needed
}


class WorkingMemory:
    """Lightweight session-state store that persists to disk between restarts."""

    def __init__(self, path: str = "data/working_memory.json"):
        self._path = Path(path)
        self._state = self._load()

    # ── Load / Save ──────────────────────────────────────────────────

    def _load(self) -> dict:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text())
                return {**_DEFAULT, **data}
            except Exception:
                pass
        return dict(_DEFAULT)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(self._state, indent=2, default=str)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with open(fd, "w") as f:
                f.write(data)
            Path(tmp).rename(self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # ── Update after each conversation turn ──────────────────────────

    def update(self, user_message: str, response: str, detected_tone: str = "neutral"):
        """Called after each message pair to update session state.

        Args:
            user_message: What the user said
            response: What Nova replied
            detected_tone: Tone detected from user_message
        """
        self._state["tone"] = detected_tone
        self._state["last_active"] = datetime.now().isoformat()
        self._state["session_count"] = self._state.get("session_count", 0) + 1

        # Prune unfinished list (keep max 5 most recent)
        if len(self._state["unfinished"]) > 5:
            self._state["unfinished"] = self._state["unfinished"][-5:]

        self._save()

    def add_unfinished(self, item: str):
        """Mark something as unfinished (e.g., a task mentioned but not completed)."""
        trimmed = item.strip()[:100]
        if trimmed and trimmed not in self._state["unfinished"]:
            self._state["unfinished"].append(trimmed)
            if len(self._state["unfinished"]) > 5:
                self._state["unfinished"].pop(0)
            self._save()

    def resolve_unfinished(self, item: str):
        """Remove an item from the unfinished list when it's completed."""
        self._state["unfinished"] = [
            x for x in self._state["unfinished"]
            if item.lower() not in x.lower()
        ]
        self._save()

    def set_calibration(self, directive: str):
        """Store a behavioral directive from the user ('be more concise')."""
        self._state["calibration"] = directive.strip()[:200]
        self._save()
        logger.info(f"Working memory calibration set: {directive[:60]}")

    def clear_calibration(self):
        """Clear any active behavioral directive."""
        self._state["calibration"] = ""
        self._save()

    def set_timezone_override(self, tz_name: str, label: str):
        """Set a temporary timezone override (e.g., user is traveling)."""
        self._state["timezone_override"] = {
            "tz": tz_name,
            "label": label,
            "set_at": datetime.now().isoformat(),
        }
        self._save()
        logger.info(f"Timezone override set: {tz_name} ({label})")

    def clear_timezone_override(self):
        """Clear timezone override (user is back home)."""
        self._state["timezone_override"] = None
        self._save()
        logger.info("Timezone override cleared (back to default)")

    @property
    def timezone_override(self) -> Optional[Dict]:
        """Return current timezone override or None."""
        return self._state.get("timezone_override")

    # ── Context for system prompt ─────────────────────────────────────

    def get_context(self) -> str:
        """Return a formatted snippet for injection into system prompts.

        Returns empty string if nothing meaningful to add.
        """
        parts = []

        tone = self._state.get("tone", "neutral")
        tone_instruction = _TONES.get(tone, "")
        if tone_instruction:
            parts.append(tone_instruction)

        calibration = self._state.get("calibration", "")
        if calibration:
            parts.append(f"📌 User instruction (active until changed): {calibration}")

        tz_override = self._state.get("timezone_override")
        if tz_override:
            parts.append(f"🌍 User is currently in {tz_override['label']} — use {tz_override['tz']} timezone for all times.")

        unfinished = self._state.get("unfinished", [])
        if unfinished:
            items = "  • " + "\n  • ".join(unfinished)
            parts.append(f"Items mentioned but not yet resolved:\n{items}")

        corrections = self.get_recent_corrections(hours=24)
        if corrections:
            corr_items = ", ".join(c["what"] for c in corrections[-2:])
            parts.append(f"Recent corrections from user: {corr_items}")

        threads = self.get_open_threads()
        if threads:
            thread_items = ", ".join(
                f"{t['topic']} [{t['status']}]" for t in threads
            )
            parts.append(f"Open threads from recent sessions: {thread_items}")

        if not parts:
            return ""

        return "WORKING MEMORY:\n" + "\n".join(parts)

    # ── Open Threads (conversation continuity across sessions) ──────

    _THREAD_EXPIRY_HOURS = 48

    def update_thread(self, topic: str, status: str = "in_progress"):
        """Track an ongoing topic thread for cross-session continuity."""
        topic = topic.strip()[:80]
        if not topic:
            return
        threads = self._state.get("open_threads", [])
        # Update existing thread if same topic
        for t in threads:
            if t["topic"].lower() == topic.lower():
                t["status"] = status
                t["updated_at"] = datetime.now().isoformat()
                self._save()
                return
        threads.append({
            "topic": topic,
            "status": status,
            "updated_at": datetime.now().isoformat(),
        })
        # Keep max 3 (most recent)
        if len(threads) > 3:
            threads = threads[-3:]
        self._state["open_threads"] = threads
        self._save()

    def resolve_thread(self, topic: str):
        """Remove a thread when the task is completed."""
        threads = self._state.get("open_threads", [])
        self._state["open_threads"] = [
            t for t in threads if topic.lower() not in t["topic"].lower()
        ]
        self._save()

    def get_open_threads(self) -> list:
        """Return active threads, pruning expired ones (>48h)."""
        threads = self._state.get("open_threads", [])
        now = datetime.now()
        cutoff_seconds = self._THREAD_EXPIRY_HOURS * 3600
        live = []
        for t in threads:
            try:
                updated = datetime.fromisoformat(t["updated_at"])
                if (now - updated).total_seconds() < cutoff_seconds:
                    live.append(t)
            except (ValueError, KeyError):
                continue
        if len(live) != len(threads):
            self._state["open_threads"] = live
            self._save()
        return live

    def is_new_session(self, gap_minutes: int = 30) -> bool:
        """Check if this is a new session (gap since last_active > threshold)."""
        last = self._state.get("last_active")
        if not last:
            return True
        try:
            last_dt = datetime.fromisoformat(last)
            elapsed = (datetime.now() - last_dt).total_seconds() / 60
            return elapsed > gap_minutes
        except (ValueError, TypeError):
            return True

    def session_context(self) -> str:
        """Return formatted open threads for session greeting injection."""
        threads = self.get_open_threads()
        if not threads:
            return ""
        lines = ["OPEN THREADS (topics from recent sessions):"]
        for t in threads:
            lines.append(f"  - {t['topic']} [{t['status']}]")
        return "\n".join(lines)

    # ── Recent Corrections (visible correction learning) ──────────

    def add_correction(self, correction: str):
        """Store a recent correction for visible acknowledgment."""
        corrections = self._state.get("recent_corrections", [])
        corrections.append({
            "what": correction.strip()[:100],
            "when": datetime.now().isoformat(),
        })
        if len(corrections) > 3:
            corrections = corrections[-3:]
        self._state["recent_corrections"] = corrections
        self._save()

    def get_recent_corrections(self, hours: int = 24) -> list:
        """Return corrections from the last N hours, pruning expired ones."""
        corrections = self._state.get("recent_corrections", [])
        cutoff = datetime.now().timestamp() - (hours * 3600)
        live = []
        for c in corrections:
            try:
                when_ts = datetime.fromisoformat(c["when"]).timestamp()
                if when_ts > cutoff:
                    live.append(c)
            except (ValueError, KeyError):
                continue
        if len(live) != len(corrections):
            self._state["recent_corrections"] = live
            self._save()
        return live

    # ── Preference Profile (structured preference model) ──────────

    _MAX_PREFS_PER_CATEGORY = 5
    _MAX_CATEGORIES = 10

    def add_preference(self, category: str, preference: str):
        """Add a structured preference learned from conversation."""
        profile = self._state.get("preference_profile", {})
        category = category.strip().lower()[:30]
        preference = preference.strip()[:80]
        if not category or not preference:
            return
        if category not in profile:
            if len(profile) >= self._MAX_CATEGORIES:
                return
            profile[category] = []
        existing_lower = [p.lower() for p in profile[category]]
        if preference.lower() not in existing_lower:
            profile[category].append(preference)
            if len(profile[category]) > self._MAX_PREFS_PER_CATEGORY:
                profile[category] = profile[category][-self._MAX_PREFS_PER_CATEGORY:]
        self._state["preference_profile"] = profile
        self._save()

    def get_preference_summary(self) -> str:
        """Return formatted preference profile for prompt injection."""
        profile = self._state.get("preference_profile", {})
        if not profile:
            return ""
        lines = ["OWNER PREFERENCES (learned from past conversations):"]
        for category, prefs in sorted(profile.items()):
            if prefs:
                lines.append(f"  {category}: {', '.join(prefs)}")
        return "\n".join(lines)

    # ── Pending Actions (confirmation loop fix) ─────────────────────

    # Max age for a pending action before it auto-expires (seconds)
    _PENDING_ACTION_TTL = 1800  # 30 minutes

    def add_pending_action(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        label: str,
        proposal_text: str,
    ):
        """Store an action that Nova proposed and is awaiting user confirmation.

        Args:
            tool_name: The tool to execute (e.g. "x_tool", "email_send")
            parameters: The parameters to pass to the tool
            label: Short human label (e.g. "post tweet", "send email to Bob")
            proposal_text: The full bot message that proposed this action
        """
        pending: List[Dict] = self._state.get("pending_actions", [])

        # Replace existing pending action from the same tool (no two pending tweets)
        pending = [p for p in pending if p.get("tool_name") != tool_name]

        pending.append({
            "tool_name": tool_name,
            "parameters": parameters,
            "label": label.strip()[:80],
            "proposal_text": proposal_text.strip()[:500],
            "created_at": time.time(),
        })

        # Cap at 3 pending actions max
        if len(pending) > 3:
            pending = pending[-3:]

        self._state["pending_actions"] = pending
        self._save()
        logger.info(f"Pending action stored: {label[:60]} (tool={tool_name})")

    def get_pending_actions(self) -> List[Dict[str, Any]]:
        """Return non-expired pending actions, cleaning up stale ones."""
        pending: List[Dict] = self._state.get("pending_actions", [])
        now = time.time()

        live = [p for p in pending if now - p.get("created_at", 0) < self._PENDING_ACTION_TTL]

        if len(live) != len(pending):
            self._state["pending_actions"] = live
            self._save()

        return live

    def pop_pending_action(self, tool_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Remove and return a pending action (by tool_name or most-recent).

        Args:
            tool_name: Specific tool to pop. If None, pops the most recent.

        Returns:
            The pending action dict, or None if nothing matches.
        """
        pending = self.get_pending_actions()
        if not pending:
            return None

        matched = None
        if tool_name:
            for p in pending:
                if p["tool_name"] == tool_name:
                    matched = p
                    break
        else:
            matched = pending[-1]  # most recent

        if matched:
            self._state["pending_actions"] = [p for p in pending if p is not matched]
            self._save()
        return matched

    def pop_all_pending_actions(self) -> List[Dict[str, Any]]:
        """Remove and return all pending actions."""
        pending = self.get_pending_actions()
        if pending:
            self._state["pending_actions"] = []
            self._save()
        return pending

    def clear_pending_actions(self):
        """Discard all pending actions (user said 'no' / 'cancel')."""
        if self._state.get("pending_actions"):
            self._state["pending_actions"] = []
            self._save()
            logger.info("All pending actions cleared")

    # ── Properties ────────────────────────────────────────────────────

    @property
    def tone(self) -> str:
        return self._state.get("tone", "neutral")

    @property
    def calibration(self) -> str:
        return self._state.get("calibration", "")
