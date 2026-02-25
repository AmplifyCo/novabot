"""Web search and fetch tool."""

import ipaddress
import aiohttp
import logging
from urllib.parse import urlparse
from typing import Optional
from .base import BaseTool
from ..types import ToolResult

logger = logging.getLogger(__name__)

# SSRF protection — block requests to private/internal networks
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("10.0.0.0/8"),         # Private Class A
    ipaddress.ip_network("172.16.0.0/12"),      # Private Class B
    ipaddress.ip_network("192.168.0.0/16"),     # Private Class C
    ipaddress.ip_network("169.254.0.0/16"),     # Link-local / AWS metadata
    ipaddress.ip_network("100.64.0.0/10"),      # Carrier-grade NAT
    ipaddress.ip_network("0.0.0.0/8"),          # "This" network
    ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),           # IPv6 private
    ipaddress.ip_network("fe80::/10"),          # IPv6 link-local
]


def _is_private_url(url: str) -> bool:
    """Check if a URL points to a private/internal IP address."""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        # Block common internal hostnames
        if hostname in ("localhost", "metadata.google.internal"):
            return True
        # Resolve and check IP
        import socket
        for info in socket.getaddrinfo(hostname, None):
            addr = ipaddress.ip_address(info[4][0])
            for net in _BLOCKED_NETWORKS:
                if addr in net:
                    return True
    except (ValueError, socket.gaierror, OSError):
        pass  # If we can't resolve, allow the request (will fail naturally)
    return False


class WebTool(BaseTool):
    """Tool for fetching web content."""

    name = "web_fetch"
    description = (
        "Tool to fetch content from a specific URL and return its text. "
        "Use when you already have a URL to read. "
        "Do NOT use for general searches — use web_search for that. "
        "If the page returns empty content (JavaScript-heavy site), use the browser tool instead."
    )
    parameters = {
        "url": {
            "type": "string",
            "description": "URL to fetch"
        }
    }

    async def execute(self, url: str) -> ToolResult:
        """Fetch content from URL.

        Args:
            url: URL to fetch

        Returns:
            ToolResult with fetched content
        """
        try:
            # SSRF protection — block private/internal network access
            if _is_private_url(url):
                logger.warning(f"SSRF blocked: {url}")
                return ToolResult(
                    success=False,
                    error="Cannot fetch internal/private network addresses"
                )

            logger.info(f"Fetching URL: {url}")

            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        content = await response.text()
                        logger.info(f"Fetched {len(content)} chars from {url}")
                        return ToolResult(
                            success=True,
                            output=content[:10000],  # Limit to 10k chars
                            metadata={"url": url, "status": response.status}
                        )
                    else:
                        return ToolResult(
                            success=False,
                            error=f"HTTP {response.status}: {url}"
                        )

        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching {url}: {e}")
            return ToolResult(
                success=False,
                error=f"Network error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return ToolResult(
                success=False,
                error=f"Error: {str(e)}"
            )
