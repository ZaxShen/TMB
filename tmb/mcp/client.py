"""MCP Client Manager — connects to external MCP servers and provides LangChain tools.

Reads config/mcp.yaml, establishes connections via langchain-mcp-adapters,
and returns tools filtered by node-level permissions.
"""

from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.tools import BaseTool

from tmb.config import load_mcp_config, get_project_root
from tmb.permissions import filter_blacklisted_output


def _build_connections(servers: dict[str, Any]) -> dict[str, dict]:
    """Convert mcp.yaml server definitions into langchain-mcp-adapters connection dicts."""
    connections = {}
    for name, cfg in servers.items():
        if "command" in cfg:
            conn: dict[str, Any] = {
                "transport": "stdio",
                "command": cfg["command"],
                "args": cfg.get("args", []),
            }
            if cfg.get("env"):
                conn["env"] = cfg["env"]
        elif "url" in cfg:
            url = cfg["url"]
            if "/sse" in url or cfg.get("transport") == "sse":
                conn = {"transport": "sse", "url": url}
            else:
                conn = {"transport": "streamable_http", "url": url}
            if cfg.get("headers"):
                conn["headers"] = cfg["headers"]
        else:
            continue
        connections[name] = conn
    return connections


def _get_agents_map(servers: dict[str, Any]) -> dict[str, list[str]]:
    """Build server_name -> allowed agents mapping from config."""
    return {
        name: cfg.get("agents", ["planner", "executor"])
        for name, cfg in servers.items()
    }


def _wrap_tool_with_blacklist(tool: BaseTool, project_root: str):
    """Wrap a tool's _run method to filter output through the blacklist scrubber."""
    original_run = tool._run

    def filtered_run(*args, **kwargs):
        result = original_run(*args, **kwargs)
        if isinstance(result, str) and project_root:
            return filter_blacklisted_output(result, project_root)
        return result

    tool._run = filtered_run


async def _load_tools_for_node(
    connections: dict[str, dict],
    agents_map: dict[str, list[str]],
    node_name: str,
) -> list[BaseTool]:
    """Connect to MCP servers and load tools for a specific node."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    allowed_servers = [
        name for name, agents in agents_map.items()
        if node_name in agents
    ]
    if not allowed_servers:
        return []

    try:
        project_root = str(get_project_root())
    except Exception:
        project_root = ""

    allowed_connections = {
        name: connections[name] for name in allowed_servers
        if name in connections
    }
    if not allowed_connections:
        return []

    client = MultiServerMCPClient(allowed_connections)
    tools = await client.get_tools()

    for t in tools:
        server_prefix = ""
        for sname in allowed_connections:
            if not t.name.startswith(f"mcp_{sname}_"):
                server_prefix = sname
                break
        if server_prefix and not t.name.startswith("mcp_"):
            t.name = f"mcp_{server_prefix}_{t.name}"
        _wrap_tool_with_blacklist(t, project_root)

    return tools


def get_mcp_tools_sync(node_name: str) -> list[BaseTool]:
    """Synchronous helper — load MCP tools for a node.

    Returns empty list if no MCP servers are configured.
    """
    mcp_cfg = load_mcp_config()
    servers = mcp_cfg.get("servers") or {}
    connections = _build_connections(servers)
    if not connections:
        return []

    agents_map = _get_agents_map(servers)

    async def _load():
        return await _load_tools_for_node(connections, agents_map, node_name)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(lambda: asyncio.run(_load())).result(timeout=30)
    else:
        return asyncio.run(_load())
