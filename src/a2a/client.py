"""A2AClient — outbound A2A protocol client for delegating tasks to external agents.

Sends JSON-RPC 2.0 requests to external A2A-compatible agents,
polls for task completion, and retrieves results.
"""

import asyncio
import logging
import os
import uuid
from typing import Any, Callable, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class A2AClient:
    """Send tasks to external A2A-compatible agents via JSON-RPC 2.0."""

    def __init__(self, credential_resolver: Optional[Callable] = None):
        self._credential_resolver = credential_resolver

    def resolve_token(self, token_str: str) -> str:
        """Resolve ${VAR} references via credential store → os.getenv."""
        if isinstance(token_str, str) and token_str.startswith("${") and token_str.endswith("}"):
            var_name = token_str[2:-1]
            if self._credential_resolver:
                resolved = self._credential_resolver(var_name)
                return resolved or ""
            return os.getenv(var_name, "")
        return token_str

    async def fetch_agent_card(self, base_url: str, timeout: int = 10) -> Optional[dict]:
        """GET /.well-known/agent-card.json from an agent's URL."""
        url = f"{base_url.rstrip('/')}/.well-known/agent-card.json"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                    if resp.status == 200:
                        return await resp.json()
                    logger.warning(f"Agent card fetch failed: {url} → HTTP {resp.status}")
                    return None
        except Exception as e:
            logger.error(f"Agent card fetch error ({url}): {e}")
            return None

    async def send_task(
        self,
        endpoint: str,
        auth_token: str,
        task_text: str,
        context_id: Optional[str] = None,
        timeout: int = 30,
    ) -> dict:
        """Send message/send to an external agent. Returns A2A response dict."""
        request_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"kind": "text", "text": task_text}],
                    "messageId": str(uuid.uuid4()),
                }
            },
        }
        if context_id:
            payload["params"]["message"]["contextId"] = context_id

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                body = await resp.json()
                if resp.status != 200:
                    error = body.get("error", {})
                    raise RuntimeError(
                        f"A2A send_task failed (HTTP {resp.status}): {error.get('message', body)}"
                    )
                if "error" in body:
                    raise RuntimeError(f"A2A JSON-RPC error: {body['error']}")
                return body.get("result", {})

    async def get_task_status(
        self,
        endpoint: str,
        auth_token: str,
        task_id: str,
        timeout: int = 15,
    ) -> dict:
        """Send tasks/get to check task status. Returns A2A Task dict."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/get",
            "params": {"id": task_id},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                body = await resp.json()
                if "error" in body:
                    raise RuntimeError(f"A2A tasks/get error: {body['error']}")
                return body.get("result", {})

    async def poll_until_done(
        self,
        endpoint: str,
        auth_token: str,
        task_id: str,
        poll_interval: int = 5,
        max_wait: int = 600,
    ) -> dict:
        """Poll tasks/get until completed/failed/canceled or timeout.

        Returns the final A2A Task dict with artifacts.
        """
        terminal_states = {"completed", "failed", "canceled", "rejected"}
        elapsed = 0

        while elapsed < max_wait:
            task = await self.get_task_status(endpoint, auth_token, task_id)
            state = task.get("status", {}).get("state", "")

            if state in terminal_states:
                return task

            logger.debug(f"A2A task {task_id}: state={state}, waiting {poll_interval}s...")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise TimeoutError(f"A2A task {task_id} did not complete within {max_wait}s")

    async def cancel_task(
        self,
        endpoint: str,
        auth_token: str,
        task_id: str,
        timeout: int = 15,
    ) -> dict:
        """Send tasks/cancel to an external agent."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/cancel",
            "params": {"id": task_id},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {auth_token}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                body = await resp.json()
                return body.get("result", {})
