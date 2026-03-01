"""Pattern Detection Engine — finds recurring time-action patterns in episodic memory.

Scans all recorded episodes, groups by tool + day of week + time of day,
and uses Gemini Flash to extract human-readable patterns.
Patterns are cached in data/patterns.json for attention engine consumption.

Background loop: scans every 12 hours. Fail-open on all errors.
"""

import asyncio
import json
import logging
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class PatternDetector:
    """Scans episodic memory for recurring behavioral patterns."""

    SCAN_INTERVAL = 43200  # 12 hours
    PATTERNS_PATH = Path("data/patterns.json")
    MIN_OCCURRENCES = 3  # need at least 3 instances to call it a pattern
    MAX_PATTERNS = 20    # cap stored patterns

    def __init__(self, episodic_memory, gemini_client=None):
        self.episodic = episodic_memory
        self.llm = gemini_client
        self._running = False

    # ── Background loop ────────────────────────────────────────────────

    async def start(self):
        """Background loop: scan every 12h."""
        self._running = True
        logger.info("PatternDetector started (12h scan cycle)")

        # Initial delay — let system warm up
        await asyncio.sleep(60)

        while self._running:
            try:
                patterns = await self.scan()
                if patterns:
                    logger.info(f"Pattern scan found {len(patterns)} patterns")
            except Exception as e:
                logger.error(f"PatternDetector error: {e}", exc_info=True)
            await asyncio.sleep(self.SCAN_INTERVAL)

    async def stop(self):
        self._running = False

    # ── Core scan ──────────────────────────────────────────────────────

    async def scan(self) -> List[Dict]:
        """One-shot scan: pull episodes, analyze frequencies, extract patterns.

        Returns list of pattern dicts saved to patterns.json.
        """
        # Step 1: Pull all episodes from LanceDB
        episodes = await self._fetch_episodes()
        if len(episodes) < self.MIN_OCCURRENCES:
            logger.debug(f"Not enough episodes ({len(episodes)}) for pattern detection")
            return []

        # Step 2: Group by tool + day of week + hour
        summary = self._build_frequency_summary(episodes)
        if not summary:
            return []

        # Step 3: Use Gemini Flash to extract patterns (or do it rule-based)
        if self.llm and getattr(self.llm, 'enabled', False):
            patterns = await self._extract_patterns_llm(summary)
        else:
            patterns = self._extract_patterns_rule(summary)

        # Step 4: Save to disk
        if patterns:
            self._save_patterns(patterns)

        return patterns

    async def _fetch_episodes(self) -> List[Dict]:
        """Pull recent episodes from episodic memory (same pattern as get_tool_success_rates)."""
        try:
            results = await self.episodic.db.search(
                query="task action activity",
                n_results=500,
                filter_metadata={"type": "episode"}
            )
            return results
        except Exception as e:
            logger.debug(f"Pattern detector episode fetch failed: {e}")
            return []

    def _build_frequency_summary(self, episodes: List[Dict]) -> str:
        """Group episodes by tool + day-of-week + time-of-day for pattern analysis."""
        # Group: tool → day_of_week → count
        tool_day: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # Group: tool → hour_bucket → count
        tool_hour: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        # Track last occurrence
        tool_last: Dict[str, str] = {}

        for ep in episodes:
            meta = ep.get("metadata", {})
            tool = meta.get("tool_used", "unknown")
            if tool == "unknown":
                continue

            timestamp = meta.get("timestamp", "")
            if not timestamp:
                continue

            try:
                dt = datetime.fromisoformat(timestamp)
                day_name = _DAYS[dt.weekday()]
                hour = dt.hour

                # Bucket hours: morning (6-10), midday (10-14), afternoon (14-18), evening (18-22), night (22-6)
                if 6 <= hour < 10:
                    bucket = "morning"
                elif 10 <= hour < 14:
                    bucket = "midday"
                elif 14 <= hour < 18:
                    bucket = "afternoon"
                elif 18 <= hour < 22:
                    bucket = "evening"
                else:
                    bucket = "night"

                tool_day[tool][day_name] += 1
                tool_hour[tool][bucket] += 1

                # Track last occurrence
                if tool not in tool_last or timestamp > tool_last[tool]:
                    tool_last[tool] = timestamp
            except (ValueError, TypeError, IndexError):
                continue

        if not tool_day:
            return ""

        # Build compact summary
        lines = []
        for tool in sorted(tool_day.keys()):
            total = sum(tool_day[tool].values())
            if total < self.MIN_OCCURRENCES:
                continue

            # Day distribution
            day_dist = ", ".join(
                f"{day}:{count}" for day, count in sorted(tool_day[tool].items(), key=lambda x: -x[1])
                if count >= 2
            )
            # Time distribution
            hour_dist = ", ".join(
                f"{bucket}:{count}" for bucket, count in sorted(tool_hour[tool].items(), key=lambda x: -x[1])
                if count >= 2
            )
            last = tool_last.get(tool, "?")[:10]
            lines.append(f"- {tool} (total={total}): days=[{day_dist}] times=[{hour_dist}] last={last}")

        return "\n".join(lines) if lines else ""

    async def _extract_patterns_llm(self, summary: str) -> List[Dict]:
        """Use Gemini Flash to extract human-readable patterns."""
        prompt = (
            "Analyze this activity data and extract recurring patterns.\n"
            "Return ONLY a JSON array of patterns. Each pattern:\n"
            '{"description": "...", "frequency": "daily|weekly|irregular", '
            '"day_of_week": "Monday|null", "tool": "...", "confidence": 0.0-1.0}\n\n'
            f"Activity data:\n{summary[:800]}\n\n"
            "Only include patterns with confidence >= 0.6. Max 10 patterns."
        )

        try:
            resp = await asyncio.wait_for(
                self.llm.generate(
                    prompt=prompt,
                    system_prompt="You are a behavioral pattern analyzer. Output only valid JSON arrays.",
                    max_tokens=300,
                ),
                timeout=3.0,
            )
            text = ""
            if isinstance(resp, str):
                text = resp.strip()
            elif isinstance(resp, dict):
                text = resp.get("text", "").strip()

            # Strip markdown fences
            text = text.replace("```json", "").replace("```", "").strip()
            patterns = json.loads(text)
            if not isinstance(patterns, list):
                return []

            # Validate and enrich
            now_iso = datetime.now().isoformat()
            valid = []
            for p in patterns[:self.MAX_PATTERNS]:
                if not isinstance(p, dict) or "description" not in p:
                    continue
                p["detected_at"] = now_iso
                p.setdefault("confidence", 0.7)
                p.setdefault("frequency", "irregular")
                valid.append(p)
            return valid

        except asyncio.TimeoutError:
            logger.debug("Pattern extraction LLM timed out")
            return self._extract_patterns_rule(summary)
        except Exception as e:
            logger.debug(f"Pattern extraction LLM failed: {e}")
            return self._extract_patterns_rule(summary)

    def _extract_patterns_rule(self, summary: str) -> List[Dict]:
        """Fallback rule-based pattern extraction when LLM unavailable."""
        patterns = []
        now_iso = datetime.now().isoformat()

        for line in summary.split("\n"):
            if not line.startswith("- "):
                continue
            # Parse: - tool (total=N): days=[...] times=[...] last=YYYY-MM-DD
            parts = line[2:].split("(total=")
            if len(parts) < 2:
                continue
            tool = parts[0].strip()
            try:
                total = int(parts[1].split(")")[0])
            except (ValueError, IndexError):
                continue

            if total >= self.MIN_OCCURRENCES:
                patterns.append({
                    "description": f"Uses {tool} regularly ({total} times recorded)",
                    "frequency": "irregular",
                    "tool": tool,
                    "confidence": min(0.5 + (total / 20), 0.9),
                    "detected_at": now_iso,
                })

        return patterns[:self.MAX_PATTERNS]

    # ── Persistence ────────────────────────────────────────────────────

    def _save_patterns(self, patterns: List[Dict]):
        """Atomic write to patterns.json."""
        self.PATTERNS_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(patterns, indent=2, default=str)
        fd, tmp = tempfile.mkstemp(dir=self.PATTERNS_PATH.parent, suffix=".tmp")
        try:
            with open(fd, "w") as f:
                f.write(data)
            Path(tmp).rename(self.PATTERNS_PATH)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def load_patterns(self) -> List[Dict]:
        """Read cached patterns from JSON."""
        if self.PATTERNS_PATH.exists():
            try:
                return json.loads(self.PATTERNS_PATH.read_text())
            except Exception:
                pass
        return []

    def get_patterns_context(self) -> str:
        """Format patterns for prompt injection. Returns '' if no patterns."""
        patterns = self.load_patterns()
        if not patterns:
            return ""

        lines = ["DETECTED PATTERNS (from past activity):"]
        for p in patterns[:10]:
            desc = p.get("description", "")
            freq = p.get("frequency", "")
            conf = p.get("confidence", 0)
            if conf >= 0.6 and desc:
                freq_label = f" ({freq})" if freq and freq != "irregular" else ""
                lines.append(f"  - {desc}{freq_label}")

        return "\n".join(lines) if len(lines) > 1 else ""
