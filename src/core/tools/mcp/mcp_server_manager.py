"""MCPServerManager — manages connections to MCP servers and registers their tools.

Config-driven: reads config/mcp_servers.json.
Each MCP server runs as a subprocess (stdio transport).
Tools are registered as MCPClientTool adapters in Nova's ToolRegistry.

Lifecycle: discover → connect → list_tools → register → (use) → shutdown.
"""

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Default config path (relative to project root)
_DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "mcp_servers.json"


class MCPServerConnection:
    """Manages a single MCP server subprocess + session."""

    def __init__(
        self,
        name: str,
        server_config: Dict[str, Any],
        credential_resolver: Optional[Callable] = None,
    ):
        self.name = name
        self.config = server_config
        self._credential_resolver = credential_resolver
        self._exit_stack: Optional[AsyncExitStack] = None
        self._session = None
        self._connected = False
        self._connect_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connected and self._session is not None

    def _resolve_env(self, env_dict: Dict[str, str]) -> Dict[str, str]:
        """Resolve ${VAR} references via credential store → os.getenv."""
        resolved = {}
        for key, value in env_dict.items():
            if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
                var_name = value[2:-1]
                if self._credential_resolver:
                    resolved_val = self._credential_resolver(var_name)
                    resolved[key] = resolved_val or ""
                else:
                    resolved[key] = os.getenv(var_name, "")
            else:
                resolved[key] = str(value)
        return resolved

    async def connect(self) -> bool:
        """Connect to MCP server (lazy, thread-safe)."""
        async with self._connect_lock:
            if self._connected:
                return True
            try:
                from mcp import ClientSession, StdioServerParameters
                from mcp.client.stdio import stdio_client

                env = self._resolve_env(self.config.get("env", {}))
                # Merge with process env so subprocess inherits PATH, etc.
                full_env = {**os.environ, **env}

                server_params = StdioServerParameters(
                    command=self.config["command"],
                    args=self.config.get("args", []),
                    env=full_env,
                )

                self._exit_stack = AsyncExitStack()
                transport = await self._exit_stack.enter_async_context(
                    stdio_client(server_params)
                )
                read_stream, write_stream = transport
                self._session = await self._exit_stack.enter_async_context(
                    ClientSession(read_stream, write_stream)
                )
                await self._session.initialize()
                self._connected = True
                logger.info(f"MCP server '{self.name}' connected")
                return True

            except ImportError:
                logger.warning(
                    f"MCP SDK not installed — cannot connect to '{self.name}'. "
                    "Install with: pip install mcp"
                )
                return False
            except Exception as e:
                logger.error(f"MCP server '{self.name}' connection failed: {e}")
                await self._cleanup()
                return False

    async def get_session(self):
        """Get session, connecting lazily if needed. Returns None on failure."""
        if not self._connected:
            success = await self.connect()
            if not success:
                return None
        return self._session

    async def list_tools(self) -> list:
        """List tools from this server. Connects lazily."""
        session = await self.get_session()
        if not session:
            return []
        try:
            response = await session.list_tools()
            return response.tools
        except Exception as e:
            logger.error(f"MCP server '{self.name}' list_tools failed: {e}")
            return []

    async def disconnect(self):
        """Disconnect from the MCP server."""
        await self._cleanup()
        logger.info(f"MCP server '{self.name}' disconnected")

    async def _cleanup(self):
        """Internal cleanup — close exit stack, reset state."""
        self._connected = False
        self._session = None
        if self._exit_stack:
            try:
                await self._exit_stack.aclose()
            except Exception:
                pass
            self._exit_stack = None


class MCPServerManager:
    """Manages all MCP server connections and tool registration.

    Reads config/mcp_servers.json at startup.
    For each enabled server: connects, discovers tools, registers as MCPClientTool.
    Supports hot-reload: re-read config, reconnect, re-register.
    """

    def __init__(
        self,
        config_path: Optional[Path] = None,
        credential_resolver: Optional[Callable] = None,
    ):
        self.config_path = config_path or _DEFAULT_CONFIG
        self._credential_resolver = credential_resolver
        self._connections: Dict[str, MCPServerConnection] = {}
        self._registered_tool_names: Dict[str, List[str]] = {}  # server → [namespaced tool names]

    def _load_config(self) -> Dict[str, Any]:
        """Load MCP server config from JSON file."""
        if not self.config_path.exists():
            logger.debug(f"MCP config not found at {self.config_path} — no MCP servers")
            return {}
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
            return data.get("servers", {})
        except Exception as e:
            logger.error(f"Failed to load MCP config: {e}")
            return {}

    async def discover_and_register(self, registry) -> Tuple[int, List[str]]:
        """Discover MCP servers, connect, list tools, register in ToolRegistry.

        Returns:
            (tools_registered, error_messages)
        """
        from .mcp_client_tool import MCPClientTool

        # Import PolicyGate risk map for injection
        try:
            from src.core.nervous_system.policy_gate import RiskLevel
            level_map = {
                "read": RiskLevel.READ,
                "write": RiskLevel.WRITE,
                "irreversible": RiskLevel.IRREVERSIBLE,
            }
            policy_gate = getattr(registry, "policy_gate", None)
        except ImportError:
            level_map = {}
            policy_gate = None

        config = self._load_config()
        if not config:
            return 0, []

        tools_registered = 0
        errors = []

        for server_name, server_config in config.items():
            if not server_config.get("enabled", True):
                logger.debug(f"MCP server '{server_name}' disabled, skipping")
                continue

            # Validate required fields
            if "command" not in server_config:
                errors.append(f"{server_name}: missing 'command' in config")
                continue

            conn = MCPServerConnection(
                name=server_name,
                server_config=server_config,
                credential_resolver=self._credential_resolver,
            )
            self._connections[server_name] = conn

            try:
                mcp_tools = await conn.list_tools()
                if not mcp_tools:
                    errors.append(f"{server_name}: no tools discovered (server may be down)")
                    continue

                # Default risk level for all tools from this server
                default_risk_str = server_config.get("risk_level", "write")
                default_risk = level_map.get(default_risk_str)
                risk_overrides = server_config.get("risk_overrides", {})
                tool_names = []

                for mcp_tool in mcp_tools:
                    # Build input schema (fallback to empty if missing)
                    input_schema = mcp_tool.inputSchema or {
                        "type": "object",
                        "properties": {},
                    }

                    adapter = MCPClientTool(
                        server_name=server_name,
                        mcp_tool_name=mcp_tool.name,
                        description=mcp_tool.description or f"Tool from {server_name}",
                        input_schema=input_schema,
                        session_provider=conn.get_session,
                    )

                    registry.register(adapter)
                    namespaced = adapter.name
                    tool_names.append(namespaced)

                    # Inject into PolicyGate risk map
                    if policy_gate and level_map:
                        if mcp_tool.name in risk_overrides:
                            risk = level_map.get(risk_overrides[mcp_tool.name], default_risk)
                        else:
                            risk = default_risk
                        if risk and hasattr(policy_gate, "TOOL_RISK_MAP"):
                            policy_gate.TOOL_RISK_MAP[namespaced] = {"_default": risk}

                    tools_registered += 1
                    logger.info(f"  MCP tool registered: {namespaced}")

                self._registered_tool_names[server_name] = tool_names
                logger.info(
                    f"MCP server '{server_name}': {len(tool_names)} tool(s) registered"
                )

            except Exception as e:
                errors.append(f"{server_name}: {e}")
                logger.error(f"MCP server '{server_name}' failed: {e}")

        return tools_registered, errors

    async def reload(self, registry) -> Tuple[int, int, List[str]]:
        """Hot-reload: disconnect all, re-read config, re-register.

        Returns:
            (new_tools_count, removed_tools_count, error_messages)
        """
        # Unregister old MCP tools
        removed = 0
        for server_name, tool_names in self._registered_tool_names.items():
            for name in tool_names:
                registry.unregister(name)
                removed += 1

        # Disconnect all servers
        for conn in self._connections.values():
            await conn.disconnect()
        self._connections.clear()
        self._registered_tool_names.clear()

        # Re-discover from fresh config
        new_tools, errors = await self.discover_and_register(registry)
        return new_tools, removed, errors

    async def shutdown(self):
        """Clean shutdown: disconnect all MCP servers."""
        for conn in self._connections.values():
            await conn.disconnect()
        self._connections.clear()
        logger.info("All MCP servers disconnected")

    def get_status(self) -> Dict[str, Any]:
        """Connection status for all servers (debug/dashboard)."""
        return {
            name: {
                "connected": conn.connected,
                "tools": self._registered_tool_names.get(name, []),
            }
            for name, conn in self._connections.items()
        }

    def get_metadata(self) -> Dict[str, Dict]:
        """Metadata for hub components (like plugin_loader.get_plugin_metadata).

        Returns dict of tool_name → metadata for all registered MCP tools.
        """
        config = self._load_config()
        meta = {}
        for server_name, tool_names in self._registered_tool_names.items():
            server_config = config.get(server_name, {})
            risk_level = server_config.get("risk_level", "write")
            for tool_name in tool_names:
                meta[tool_name] = {
                    "safe_readonly": risk_level == "read",
                    "persona": None,
                    "description": f"MCP tool from {server_name}",
                    "risk_map": {"_default": risk_level},
                    "source": "mcp",
                }
        return meta
