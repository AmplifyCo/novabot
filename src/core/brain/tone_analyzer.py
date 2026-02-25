"""Tone Analyzer — detect emotional register from incoming messages.

Rule-based (zero latency, no LLM calls) with scoring-based classification.
Feeds into WorkingMemory so the detected tone persists and shapes responses.

Security: no external calls, no data storage. Pure text analysis only.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ToneSignal:
    """The detected tone of an incoming message."""
    register: str           # neutral | urgent | stressed | relaxed | formal
    urgency: float          # 0.0 – 1.0
    brevity_preferred: bool # True = keep replies short
    note: str               # human-readable reason (for logging)


# ── Negation prefixes that suppress a keyword match ──────────────────
# Matches "no", "not", "no longer", "nothing", "never" right before the word.
_NEGATION_PREFIX = r"(?<!\w)(no|not|no longer|nothing|never|don'?t|doesn'?t|isn'?t|aren'?t|wasn'?t|weren'?t)\s+"


# ── Signal patterns ──────────────────────────────────────────────────
# Each entry is (regex, weight). Weights let multiple weak signals
# accumulate instead of a single false-positive keyword deciding the tone.

_URGENT_PATTERNS = [
    (r"\basap\b", 2),
    (r"\burgent\b", 2),
    (r"\bquick(ly)?\b", 1),
    # "now" only counts when it carries urgency context
    (r"\b(do|need|send|fix|handle|finish|call|get|reply|respond)\b.{0,15}\bnow\b", 2),
    (r"\bright now\s*[!.]", 2),
    (r"\bnow\s*!+", 2),
    (r"\bimmediately\b", 2),
    (r"\bfast\b", 1),
    (r"\bhurry\b", 2),
    (r"\bno time\b", 2),
    (r"\bin (\d+ )?(min|hour|sec)\b", 1),
    (r"!!+", 1),
]

_STRESSED_PATTERNS = [
    (r"\bstress(ed|ful)?\b", 2),
    (r"\bworried\b", 2),
    (r"\bpanic(k?ing)?\b", 2),
    (r"\bproblem\b", 1),        # negation-checked below
    (r"\bcrisis\b", 2),
    (r"\bmess(ed)? up\b", 2),
    (r"\bwrong\b", 1),          # negation-checked below
    (r"\bfailed?\b", 1),        # negation-checked below
    (r"\bbroken\b", 1),         # negation-checked below
    (r"\bscrew(ed)?\b", 2),
    (r"\bugh\b", 2),
    (r"\bhelp me\b", 2),
    (r"\bcan('t| not) figure\b", 2),
]

_RELAXED_PATTERNS = [
    (r"\bwhen you get a chance\b", 3),
    (r"\bno rush\b", 3),
    (r"\btake your time\b", 3),
    (r"\bwhenever\b", 2),
    (r"\bjust curious\b", 2),
    (r"\bby the way\b", 2),
    (r"\bfyi\b", 2),
    (r"\bthinking about\b", 1),
    (r"\bwondering\b", 1),
    (r"\bno problem\b", 2),
    (r"\bno worries\b", 2),
    (r"\bnothing wrong\b", 2),
]

_FORMAL_PATTERNS = [
    (r"\bplease\b.*\bkindly\b", 2),
    (r"\bregarding\b", 1),
    (r"\bherewith\b", 2),
    (r"\bpursuant\b", 2),
    (r"\bforthwith\b", 2),
    (r"\benclosed\b", 1),
    (r"\bdear\b.*\bsincerely\b", 2),
    (r"\brespectfully\b", 1),
]


# Words where a preceding negation flips their meaning (e.g. "no problem"
# should NOT count as stressed). Only applied to stressed / urgent patterns.
_NEGATION_SENSITIVE = {
    r"\bproblem\b", r"\bwrong\b", r"\bfailed?\b", r"\bbroken\b",
    r"\bfast\b", r"\bquick(ly)?\b",
}


def _score(text: str, patterns: list) -> int:
    """Sum weights of all matching patterns, suppressing negation-sensitive
    matches when preceded by a negation word."""
    total = 0
    for pattern, weight in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if not m:
            continue
        # Negation check for sensitive words
        if pattern in _NEGATION_SENSITIVE:
            start = m.start()
            prefix = text[:start]
            # Look for negation word just before the match
            if re.search(_NEGATION_PREFIX + r"$", prefix, re.IGNORECASE):
                continue
        total += weight
    return total


def analyze(message: str) -> ToneSignal:
    """Detect the emotional tone of an incoming message.

    Uses a scoring approach: all categories are scored in parallel and the
    highest score wins. Relaxed signals can override spurious urgent/stressed
    hits. Negation-aware checks prevent "no problem" from counting as stressed.

    Args:
        message: Raw user message text

    Returns:
        ToneSignal with register, urgency, and brevity preference
    """
    text = message.strip()
    word_count = len(text.split())

    # Empty or very short messages — treat as neutral
    if word_count < 2:
        return ToneSignal("neutral", 0.2, True, "very short message")

    # Score every category
    relaxed_score = _score(text, _RELAXED_PATTERNS)
    urgent_score  = _score(text, _URGENT_PATTERNS)
    stressed_score = _score(text, _STRESSED_PATTERNS)
    formal_score  = _score(text, _FORMAL_PATTERNS)

    # Relaxed signals dampen urgent/stressed (e.g. "no rush" cancels "quick")
    if relaxed_score > 0:
        urgent_score  = max(0, urgent_score - relaxed_score)
        stressed_score = max(0, stressed_score - relaxed_score)

    # Pick the winning register (threshold of 2 to avoid single weak match)
    scores = {
        "urgent":  urgent_score,
        "stressed": stressed_score,
        "formal":  formal_score,
        "relaxed": relaxed_score,
    }
    best = max(scores, key=scores.get)
    best_val = scores[best]

    if best_val >= 2:
        if best == "urgent":
            return ToneSignal("urgent", 0.9, True, "urgency keywords detected")
        if best == "stressed":
            return ToneSignal("stressed", 0.7, False, "stress keywords detected")
        if best == "formal":
            return ToneSignal("formal", 0.3, False, "formal language detected")
        if best == "relaxed":
            return ToneSignal("relaxed", 0.1, False, "relaxed phrasing detected")

    # Heuristic: very short messages tend to be urgent / expect brief replies
    if word_count <= 5:
        return ToneSignal("neutral", 0.5, True, "short message")

    return ToneSignal("neutral", 0.2, False, "no strong signal")


def calibration_instruction(tone: ToneSignal) -> str:
    """Return a brief system-prompt instruction based on detected tone.

    Args:
        tone: ToneSignal from analyze()

    Returns:
        One-line instruction to append to the system prompt, or ""
    """
    instructions = {
        "urgent":  "Be brief and direct — the user is in a hurry. Lead with the answer.",
        "stressed": "Be calm and clear — the user seems under pressure. Avoid jargon.",
        "relaxed":  "The user is relaxed — you can be conversational and thorough.",
        "formal":   "Match professional tone — be precise and structured.",
        "neutral":  "",
    }
    return instructions.get(tone.register, "")
