"""Tool bindings for the Executor and Validator nodes."""

from aide.tools.shell import create_shell_tool
from aide.tools.filesystem import create_file_read_tool, create_file_write_tool
from aide.tools.search import create_search_tool


def get_tools_for_node(tool_names: list[str], project_root: str) -> list:
    """Return LangChain tool instances for the given tool name list."""
    registry = {
        "shell": lambda: create_shell_tool(project_root),
        "file_read": lambda: create_file_read_tool(project_root),
        "file_write": lambda: create_file_write_tool(project_root),
        "search": lambda: create_search_tool(project_root),
    }
    tools = []
    for name in tool_names:
        factory = registry.get(name)
        if factory is None:
            raise ValueError(f"Unknown tool: {name}")
        tools.append(factory())
    return tools
