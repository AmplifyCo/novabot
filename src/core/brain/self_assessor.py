"""Self-Assessor — lightweight quality assessment + multi-turn deliberation.

3C: Every substantive response gets a quick confidence check (high/medium/low).
    Low-confidence areas are flagged naturally: "I'm confident about X but Y is thin."
3D: Complex judgment questions trigger multi-source deliberation:
    EVIDENCE → TENSIONS → RECOMMENDATION → CAVEATS structure.

Both use Gemini Flash with tight timeouts. Fail-open on all errors.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SelfAssessment:
    """Result of a lightweight quality self-assessment."""
    confidence: str = "high"         # "high" | "medium" | "low"
    weak_areas: List[str] = field(default_factory=list)  # ["competitor analysis"]
    suggestion: str = ""             # "Want me to dig deeper into X?"


class SelfAssessor:
    """Lightweight quality self-assessment + multi-turn deliberation."""

    # Keywords that trigger deliberation (3D)
    _DELIBERATION_TRIGGERS = [
        "should i", "should we", "pros and cons", "trade-off", "tradeoff",
        "compare", "recommend", "which option", "best way to", "best approach",
        "advantages and disadvantages", "what would you suggest", "weigh",
        "better option", "or should", "versus", " vs ",
    ]

    def __init__(self, gemini_client=None):
        self.llm = gemini_client

    # ── 3C: Quality Self-Assessment ────────────────────────────────────

    async def assess_response(
        self,
        query: str,
        response: str,
        persona: str = "",
    ) -> Optional[SelfAssessment]:
        """Evaluate response confidence. Returns None on error (fail-open).

        Uses Gemini Flash with tight prompt. ~0.5-1s latency.
        Only called for substantive responses (>150 chars).
        """
        if not self.llm or not getattr(self.llm, 'enabled', False):
            return None

        # Skip trivial responses
        if len(response) < 150:
            return None

        prompt = (
            "Assess this response's quality. Reply ONLY with valid JSON:\n"
            '{"confidence": "high|medium|low", "weak_areas": ["area1"], "suggestion": "..."}\n\n'
            "Rules:\n"
            "- high: response is complete, accurate, well-grounded\n"
            "- medium: mostly good but some areas could be stronger\n"
            "- low: missing key information, speculative, or thin in parts\n"
            "- weak_areas: list specific topics that are thin (max 2)\n"
            "- suggestion: if low, suggest what to research further (1 sentence). Empty for high/medium.\n\n"
            f"Question: {query[:300]}\n"
            f"Response: {response[:500]}\n"
        )

        try:
            resp = await asyncio.wait_for(
                self.llm.generate(
                    prompt=prompt,
                    system_prompt="You are a response quality assessor. Output only JSON.",
                    max_tokens=200,
                ),
                timeout=2.0,
            )
            text = ""
            if isinstance(resp, str):
                text = resp.strip()
            elif isinstance(resp, dict):
                text = resp.get("text", "").strip()

            # Strip markdown fences
            text = text.replace("```json", "").replace("```", "").strip()

            data = json.loads(text)
            return SelfAssessment(
                confidence=data.get("confidence", "high"),
                weak_areas=data.get("weak_areas", [])[:2],
                suggestion=data.get("suggestion", "")[:150],
            )
        except asyncio.TimeoutError:
            logger.debug("Self-assessment timed out — skipping")
            return None
        except Exception as e:
            logger.debug(f"Self-assessment failed — skipping: {e}")
            return None

    def format_assessment(self, assessment: SelfAssessment) -> str:
        """Format assessment as a natural suffix for the response.

        Returns '' for high/medium confidence (only surface low).
        """
        if not assessment or assessment.confidence != "low":
            return ""

        if assessment.suggestion:
            return f"\n\n_{assessment.suggestion}_"
        elif assessment.weak_areas:
            areas = " and ".join(assessment.weak_areas[:2])
            return f"\n\n_Note: The {areas} part could use more depth — want me to dig deeper?_"
        return ""

    # ── 3D: Multi-Turn Deliberation ────────────────────────────────────

    @staticmethod
    def needs_deliberation(message: str, intent: Optional[Dict] = None) -> bool:
        """Detect if a message needs multi-turn deliberation.

        Zero LLM calls — keyword-based detection.
        """
        msg_lower = message.lower()
        return any(trigger in msg_lower for trigger in SelfAssessor._DELIBERATION_TRIGGERS)

    async def deliberate(
        self,
        query: str,
        brain_context: str = "",
        episodic_context: str = "",
    ) -> str:
        """Multi-source evidence gathering for complex judgment questions.

        Produces structured EVIDENCE → TENSIONS → RECOMMENDATION → CAVEATS.
        Returns enriched reasoning (injected where preflight_reasoning goes).

        Uses Gemini Flash, 500 tokens, 5s timeout. Fail-open (returns '').
        """
        if not self.llm or not getattr(self.llm, 'enabled', False):
            return ""

        context_parts = []
        if brain_context:
            context_parts.append(f"Known context:\n{brain_context[:400]}")
        if episodic_context:
            context_parts.append(f"Past experience:\n{episodic_context[:400]}")
        context = "\n\n".join(context_parts) if context_parts else "No prior context available."

        prompt = (
            "This question requires careful judgment. Deliberate before answering:\n\n"
            "1. EVIDENCE: What do we know from context and experience? (cite specific facts)\n"
            "2. TENSIONS: Where does the evidence conflict or where are the trade-offs?\n"
            "3. RECOMMENDATION: Given the trade-offs, what's the best approach and why?\n"
            "4. CAVEATS: What are we less sure about? What would change the recommendation?\n\n"
            f"Question: {query[:500]}\n\n"
            f"{context}\n\n"
            "Respond using the numbered format above. Be concise but thorough."
        )

        try:
            resp = await asyncio.wait_for(
                self.llm.generate(
                    prompt=prompt,
                    system_prompt="You are a deliberation engine. Produce structured reasoning with evidence and trade-offs.",
                    max_tokens=500,
                ),
                timeout=5.0,
            )
            text = ""
            if isinstance(resp, str):
                text = resp.strip()
            elif isinstance(resp, dict):
                text = resp.get("text", "").strip()

            # Sanity check
            if len(text) < 30 or len(text) > 2000:
                return ""
            return text
        except asyncio.TimeoutError:
            logger.debug("Deliberation timed out — falling back to standard preflight")
            return ""
        except Exception as e:
            logger.debug(f"Deliberation failed — falling back: {e}")
            return ""
