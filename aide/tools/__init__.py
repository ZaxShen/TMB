"""Tool bindings for agent nodes."""

from aide.tools.shell import create_shell_tool
from aide.tools.filesystem import create_file_read_tool, create_file_write_tool
from aide.tools.search import create_search_tool
from aide.tools.skills import create_skill_tool


def get_tools_for_node(tool_names: list[str], project_root: str, node_name: str = "executor") -> list:
    """Return LangChain tool instances scoped to a node.
    node_name is used for per-node access control (e.g. executor can't read GOALS.md)."""
    registry = {
        "shell": lambda: create_shell_tool(project_root),
        "file_read": lambda: create_file_read_tool(project_root, node_name),
        "file_write": lambda: create_file_write_tool(project_root, node_name),
        "search": lambda: create_search_tool(project_root),
        "skill_create": lambda: create_skill_tool(creator_node=node_name),
    }
    tools = []
    for name in tool_names:
        factory = registry.get(name)
        if factory is None:
            raise ValueError(f"Unknown tool: {name}")
        tools.append(factory())
    return tools
