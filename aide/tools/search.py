"""Code search tool — ripgrep wrapper sandboxed to project root."""

from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool


def create_search_tool(project_root: str):
    root = Path(project_root).resolve()

    @tool
    def search(pattern: str, glob: str = "") -> str:
        """Search for a regex pattern in the project using ripgrep. Optional glob filter (e.g. '*.py')."""
        cmd = ["rg", "--no-heading", "--line-number", pattern, str(root)]
        if glob:
            cmd.insert(3, f"--glob={glob}")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                return result.stdout[:10_000]  # cap output size
            if result.returncode == 1:
                return "No matches found."
            return f"[error] {result.stderr}"
        except subprocess.TimeoutExpired:
            return "[error] Search timed out after 30 seconds."
        except FileNotFoundError:
            return "[error] ripgrep (rg) is not installed."

    return search
