"""MCP Server — exposes Baymax's store and workflow to external MCP hosts.

Start with:
    uv run main.py serve              # stdio transport (Claude Desktop, Cursor)
    uv run main.py serve --http 8080  # HTTP transport
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from baymax.config import _BAYMAX_ROOT
from baymax.store import Store


mcp = FastMCP(
    "baymax",
    instructions=(
        "Baymax is a multi-agent software engineering framework. "
        "Use these tools to inspect issues, tasks, skills, and workflow state."
    ),
)


# ── Tools ─────────────────────────────────────────────────


@mcp.tool()
def baymax_list_issues(limit: int = 20) -> str:
    """List recent issues with their status.

    Args:
        limit: Maximum number of issues to return (default 20)
    """
    store = Store()
    rows = store._conn.execute(
        "SELECT id, objective, status, created_at, closed_at "
        "FROM issues ORDER BY id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    if not rows:
        return "No issues found."
    results = []
    for r in rows:
        results.append({
            "id": r["id"],
            "objective": r["objective"],
            "status": r["status"],
            "created_at": r["created_at"],
            "closed_at": r["closed_at"],
        })
    return json.dumps(results, indent=2)


@mcp.tool()
def baymax_get_tasks(issue_id: int) -> str:
    """Get task overview for an issue — lightweight metadata, no full descriptions.

    Args:
        issue_id: The issue ID to get tasks for
    """
    store = Store()
    tasks = store.get_tasks_overview(issue_id)
    if not tasks:
        return f"No tasks found for issue #{issue_id}."
    return json.dumps(tasks, indent=2)


@mcp.tool()
def baymax_get_ledger(issue_id: int) -> str:
    """Get ledger summary for an issue — event types and summaries, no JSON blobs.

    Args:
        issue_id: The issue ID to get the ledger for
    """
    store = Store()
    entries = store.get_ledger_overview(issue_id)
    if not entries:
        return f"No ledger entries for issue #{issue_id}."
    return json.dumps(entries, indent=2)


@mcp.tool()
def baymax_get_skills() -> str:
    """List all active skills with effectiveness scores."""
    store = Store()
    skills = store.get_all_skills()
    return json.dumps(skills, indent=2)


@mcp.tool()
def baymax_query_branch(prefix: str) -> str:
    """Query all tasks under a branch prefix (e.g. '1' gets '1', '1.1', '1.1.1').

    Args:
        prefix: The branch ID prefix to search for
    """
    store = Store()
    tree = store.get_task_tree(prefix)
    if not tree:
        return f"No tasks found matching branch prefix '{prefix}'."
    return json.dumps(tree, indent=2)


@mcp.tool()
def baymax_quick_task(instruction: str) -> str:
    """Run a quick task — the Planner handles it directly with no downstream agents.

    Args:
        instruction: What to do (e.g. 'update FLOWCHART based on current codebase')
    """
    from baymax.nodes.gatekeeper import gatekeeper as gk_func
    from baymax.nodes.planner import planner_quick_task

    store = Store()
    issue_id = store.create_issue(f"Quick: {instruction[:120]}", "")
    store.log(issue_id, None, "system", "quick_task_started", {},
              summary=f"Quick: {instruction[:150]}")

    gk_state = {"objective": instruction, "project_context": "", "messages": []}
    gk_result = gk_func(gk_state)
    project_context = gk_result.get("project_context", "")

    result = planner_quick_task(instruction, project_context, issue_id)

    store.close_issue(issue_id, "completed")
    return result or "Quick task completed."


@mcp.tool()
def baymax_export_report(issue_id: int) -> str:
    """Export a full human-readable markdown report for an issue.

    Args:
        issue_id: The issue ID to generate the report for
    """
    store = Store()
    return store.export_report_md(issue_id)


# ── Resources ─────────────────────────────────────────────


@mcp.resource("baymax://issues")
def resource_issues() -> str:
    """All issues in the Baymax database."""
    return baymax_list_issues(limit=100)


@mcp.resource("baymax://issues/{issue_id}")
def resource_issue(issue_id: int) -> str:
    """Detailed view of a single issue including tasks and ledger."""
    store = Store()
    issue = store.get_issue(issue_id)
    if not issue:
        return f"Issue #{issue_id} not found."
    tasks = store.get_tasks_overview(issue_id)
    ledger = store.get_ledger_overview(issue_id)
    return json.dumps({
        "issue": dict(issue),
        "tasks": tasks,
        "ledger": ledger,
    }, indent=2)


@mcp.resource("baymax://skills")
def resource_skills() -> str:
    """All active skills with metadata."""
    return baymax_get_skills()


@mcp.resource("baymax://blueprint")
def resource_blueprint() -> str:
    """Current doc/BLUEPRINT.md content."""
    path = _BAYMAX_ROOT / "doc" / "BLUEPRINT.md"
    if path.exists():
        return path.read_text()
    return "No blueprint found."


def run_server(transport: str = "stdio", port: int = 8000):
    """Start the Baymax MCP server."""
    if transport == "stdio":
        mcp.run(transport="stdio")
    elif transport == "http":
        mcp.run(transport="streamable-http", host="127.0.0.1", port=port)
    else:
        raise ValueError(f"Unsupported transport: {transport}. Use 'stdio' or 'http'.")
