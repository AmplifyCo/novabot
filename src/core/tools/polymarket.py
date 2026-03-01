"""Polymarket Tool — read prediction market data (events, odds, trends).

Uses the public Gamma API — no API key, no auth, no wallet needed.
Read-only: never places trades or modifies anything.

API docs: https://docs.polymarket.com/developers/gamma-markets-api/overview
Base URL: https://gamma-api.polymarket.com
Rate limit: 60 requests/minute (public)
"""

import json
import logging
from typing import Optional

import aiohttp

from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)

_GAMMA_URL = "https://gamma-api.polymarket.com"


def _format_odds(outcomes_raw, prices_raw) -> str:
    """Convert outcomes + outcomePrices to readable percentages.

    Args:
        outcomes_raw: '["Yes", "No"]' (JSON string) or list
        prices_raw: '["0.65", "0.35"]' (JSON string) or list

    Returns:
        "Yes: 65% | No: 35%"
    """
    try:
        outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw
        prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
        pairs = []
        for o, p in zip(outcomes, prices):
            pct = float(p) * 100
            pairs.append(f"{o}: {pct:.0f}%")
        return " | ".join(pairs)
    except Exception:
        return str(prices_raw)


def _format_volume(vol) -> str:
    """Format volume as human-readable dollar amount."""
    try:
        v = float(vol)
        if v >= 1_000_000:
            return f"${v / 1_000_000:.1f}M"
        elif v >= 1_000:
            return f"${v / 1_000:.1f}K"
        else:
            return f"${v:,.0f}"
    except (ValueError, TypeError):
        return str(vol)


class PolymarketTool(BaseTool):
    """Read-only tool for querying Polymarket prediction market data.

    No API key needed — all endpoints are public.
    """

    name = "polymarket"
    description = (
        "Read prediction market data from Polymarket. Use for checking odds, "
        "trending events, searching markets, or exploring categories. "
        "Operations: 'trending' (top events by volume), 'search' (find by keyword), "
        "'get_event' (single event details + odds), 'categories' (list available topics). "
        "Read-only — never places trades. Useful for gauging public sentiment on "
        "elections, sports, crypto, tech, AI, and world events."
    )
    parameters = {
        "operation": {
            "type": "string",
            "enum": ["trending", "search", "get_event", "categories"],
            "description": (
                "'trending': top events by 24h trading volume (optionally filter by category). "
                "'search': find events/markets matching a keyword query. "
                "'get_event': get detailed info + odds for a specific event (by slug from URL). "
                "'categories': list available categories/tags for filtering."
            ),
        },
        "query": {
            "type": "string",
            "description": "Search query. Required for 'search'.",
        },
        "category": {
            "type": "string",
            "description": (
                "Filter by category slug for 'trending'. "
                "Common: 'sports', 'politics', 'crypto', 'ai', 'tech', 'business', "
                "'finance', 'pop-culture', 'science'. Use 'categories' operation to see all."
            ),
        },
        "slug": {
            "type": "string",
            "description": "Event slug for 'get_event'. Extract from Polymarket URL path.",
        },
        "limit": {
            "type": "integer",
            "description": "Number of results to return (default: 5, max: 20).",
        },
    }

    def __init__(self):
        pass  # No credentials needed

    def to_anthropic_tool(self):
        """Override — only operation is required."""
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
        operation: str,
        query: Optional[str] = None,
        category: Optional[str] = None,
        slug: Optional[str] = None,
        limit: int = 5,
        **kwargs,
    ) -> ToolResult:
        limit = min(max(int(limit), 1), 20)

        if operation == "trending":
            return await self._trending(limit, category)
        elif operation == "search":
            if not query or not query.strip():
                return ToolResult(success=False, error="'query' is required for search")
            return await self._search(query.strip(), limit)
        elif operation == "get_event":
            if not slug or not slug.strip():
                return ToolResult(success=False, error="'slug' is required for get_event")
            return await self._get_event(slug.strip())
        elif operation == "categories":
            return await self._categories()
        else:
            return ToolResult(success=False, error=f"Unknown operation: {operation}")

    # ── Private helpers ───────────────────────────────────────────────────

    async def _trending(self, limit: int, category: Optional[str]) -> ToolResult:
        """Fetch top events by 24h volume, optionally filtered by category."""
        params = {
            "active": "true",
            "closed": "false",
            "limit": str(limit),
        }
        if category:
            params["tag_slug"] = category.strip().lower()

        data = await self._get("/events", params)
        if isinstance(data, ToolResult):
            return data  # error

        if not data:
            cat_msg = f" in '{category}'" if category else ""
            return ToolResult(success=True, output=f"No active events found{cat_msg}.")

        # Sort by volume24hr descending (API may not guarantee order)
        try:
            data.sort(key=lambda e: float(e.get("volume24hr", 0) or 0), reverse=True)
        except Exception:
            pass

        lines = [f"Polymarket Trending{f' ({category})' if category else ''} — Top {len(data)} by 24h volume:\n"]
        for e in data:
            title = e.get("title", "Untitled")
            vol24h = _format_volume(e.get("volume24hr", 0))
            tags = [t["label"] for t in e.get("tags", []) if t.get("label")][:3]
            tag_str = f" [{', '.join(tags)}]" if tags else ""

            lines.append(f"• {title}{tag_str}")
            lines.append(f"  Volume (24h): {vol24h}")

            for m in e.get("markets", [])[:3]:
                q = m.get("question", "")
                odds = _format_odds(m.get("outcomes", "[]"), m.get("outcomePrices", "[]"))
                lines.append(f"  → {q}: {odds}")
            lines.append("")

        return ToolResult(success=True, output="\n".join(lines))

    async def _search(self, query: str, limit: int) -> ToolResult:
        """Search events by keyword using tag_slug or title matching."""
        # Try the events endpoint with text_query first (undocumented but works on some deployments)
        # Fall back to fetching active events and filtering client-side
        params = {
            "active": "true",
            "closed": "false",
            "limit": str(min(limit * 5, 100)),  # fetch more, filter client-side
        }
        data = await self._get("/events", params)
        if isinstance(data, ToolResult):
            return data

        if not data:
            return ToolResult(success=True, output=f"No events found for '{query}'.")

        # Client-side keyword filter
        query_lower = query.lower()
        matched = []
        for e in data:
            title = (e.get("title") or "").lower()
            desc = (e.get("description") or "").lower()
            tags = " ".join(t.get("label", "") for t in e.get("tags", [])).lower()
            market_qs = " ".join(m.get("question", "") for m in e.get("markets", [])).lower()
            if query_lower in title or query_lower in desc or query_lower in tags or query_lower in market_qs:
                matched.append(e)

        if not matched:
            return ToolResult(success=True, output=f"No events matching '{query}' found among active markets.")

        matched = matched[:limit]
        lines = [f"Polymarket search results for '{query}' ({len(matched)} events):\n"]
        for e in matched:
            title = e.get("title", "Untitled")
            vol24h = _format_volume(e.get("volume24hr", 0))
            slug = e.get("slug", "")
            lines.append(f"• {title}")
            lines.append(f"  Slug: {slug} | Volume (24h): {vol24h}")
            for m in e.get("markets", [])[:3]:
                q = m.get("question", "")
                odds = _format_odds(m.get("outcomes", "[]"), m.get("outcomePrices", "[]"))
                lines.append(f"  → {q}: {odds}")
            lines.append("")

        return ToolResult(success=True, output="\n".join(lines))

    async def _get_event(self, slug: str) -> ToolResult:
        """Get detailed info for a single event by slug."""
        data = await self._get(f"/events/slug/{slug}")
        if isinstance(data, ToolResult):
            return data

        if not data:
            return ToolResult(success=False, error=f"Event not found: {slug}")

        # /events/slug/{slug} returns the event directly (not a list)
        e = data if isinstance(data, dict) else data[0] if data else {}
        title = e.get("title", "Untitled")
        desc = (e.get("description") or "")[:300]
        vol = _format_volume(e.get("volume", 0))
        vol24h = _format_volume(e.get("volume24hr", 0))
        liquidity = _format_volume(e.get("liquidity", 0))
        tags = [t["label"] for t in e.get("tags", []) if t.get("label")]
        end_date = e.get("endDate", "")[:10]

        lines = [
            f"Polymarket Event: {title}",
            f"Tags: {', '.join(tags) if tags else 'None'}",
            f"Volume: {vol} (24h: {vol24h}) | Liquidity: {liquidity}",
        ]
        if end_date:
            lines.append(f"End date: {end_date}")
        if desc:
            lines.append(f"Description: {desc}")
        lines.append("")

        markets = e.get("markets", [])
        if markets:
            lines.append(f"Markets ({len(markets)}):")
            for m in markets[:10]:
                q = m.get("question", "")
                odds = _format_odds(m.get("outcomes", "[]"), m.get("outcomePrices", "[]"))
                vol_m = _format_volume(m.get("volume", 0))
                lines.append(f"  • {q}")
                lines.append(f"    Odds: {odds} | Volume: {vol_m}")

        return ToolResult(success=True, output="\n".join(lines))

    async def _categories(self) -> ToolResult:
        """List major categories/tags available for filtering."""
        data = await self._get("/tags")
        if isinstance(data, ToolResult):
            return data

        if not data:
            return ToolResult(success=True, output="No categories found.")

        # Filter to well-known categories (skip micro-tags)
        _KNOWN_SLUGS = {
            "politics", "sports", "crypto", "ai", "tech", "business", "finance",
            "science", "pop-culture", "entertainment", "elections", "world",
            "health", "music", "gaming", "stocks", "climate", "education",
        }
        major = [t for t in data if t.get("slug", "") in _KNOWN_SLUGS]
        # If few known ones found, also include tags with forceShow
        if len(major) < 5:
            shown = {t.get("slug") for t in major}
            for t in data:
                if t.get("forceShow") and t.get("slug") not in shown:
                    major.append(t)

        if not major:
            # Fall back to first N tags
            major = data[:20]

        lines = ["Polymarket categories (use slug with 'trending' category filter):\n"]
        for t in sorted(major, key=lambda x: x.get("label", "")):
            lines.append(f"  • {t.get('label', '?')} (slug: {t.get('slug', '?')})")

        return ToolResult(success=True, output="\n".join(lines))

    async def _get(self, path: str, params: Optional[dict] = None):
        """Make a GET request to the Gamma API.

        Returns parsed JSON data or a ToolResult error.
        """
        url = f"{_GAMMA_URL}{path}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=15)
                ) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    elif resp.status == 429:
                        return ToolResult(
                            success=False,
                            error="Polymarket API rate limit reached (60 req/min). Try again shortly.",
                        )
                    else:
                        body = await resp.text()
                        logger.warning(f"Polymarket API {resp.status}: {body[:200]}")
                        return ToolResult(
                            success=False,
                            error=f"Polymarket API error {resp.status}: {body[:150]}",
                        )
        except aiohttp.ClientError as e:
            logger.error(f"Polymarket network error: {e}")
            return ToolResult(success=False, error=f"Network error: {e}")
        except Exception as e:
            logger.error(f"Polymarket request failed: {e}", exc_info=True)
            return ToolResult(success=False, error=f"Request failed: {e}")
