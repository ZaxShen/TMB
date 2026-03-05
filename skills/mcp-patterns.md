# Skill: MCP Patterns

> Patterns for using and generating MCP (Model Context Protocol) servers within AIDE.

---

## Using MCP Tools

MCP tools from external servers are auto-discovered and prefixed:

```
mcp_{server_name}_{tool_name}
```

For example, if a Notion server is configured, tools appear as:
- `mcp_notion_search_pages`
- `mcp_notion_create_page`

No special invocation — call them like any other tool.

## Checking Available MCP Servers

```python
from aide.config import load_mcp_config

cfg = load_mcp_config()
servers = cfg.get("servers", {})
for name, server_cfg in servers.items():
    agents = server_cfg.get("agents", [])
    print(f"{name}: accessible by {agents}")
```

## Generating New MCP Servers

Use the `mcp_generate` tool with one of three templates:

```python
# REST API wrapper
mcp_generate(name="my-api", template="rest_api", base_url="https://api.example.com")

# Database connector
mcp_generate(name="my-db", template="database", db_path="/path/to/db.sqlite")

# File-based resource server
mcp_generate(name="my-files", template="file_based", root_dir="/path/to/files")
```

Generated servers are auto-registered in `config/mcp.yaml`.

## Permission Model

- MCP tool access is gated by `agents` in `config/mcp.yaml`
- Tool output goes through the blacklist scrubber (same as shell output)
- External MCP hosts connecting to AIDE's server get read-only access

## Rules

1. **Never hardcode API tokens** in MCP server code — use `${VAR}` env references in `mcp.yaml`.
2. **Check `agents` field** before assuming a tool is available — not all nodes have the same MCP access.
3. **Prefer existing MCP servers** from the community before generating custom ones.
4. **Generated servers go to `mcp_servers/`** — never into `aide/` (engine internals).
