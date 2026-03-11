"""Code search tool — ripgrep wrapper, blacklist patterns excluded."""

from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool

from tmb.permissions import filter_blacklisted_output
from tmb.config import load_project_config


def create_search_tool(project_root: str):
    root = Path(project_root).resolve()

    @tool
    def search(pattern: str, glob: str = "") -> str:
        """Search for a regex pattern in the project using ripgrep. Optional glob filter (e.g. '*.py')."""
        cfg = load_project_config()
        blacklist = cfg.get("blacklist", [])

        cmd = ["rg", "--no-heading", "--line-number", pattern, str(root)]
        if glob:
            cmd.insert(3, f"--glob={glob}")
        for bl in blacklist:
            cmd.insert(3, f"--glob=!{bl}")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                output = result.stdout[:10_000]
                return filter_blacklisted_output(output, str(root))
            if result.returncode == 1:
                return "No matches found."
            return f"[error] {result.stderr}"
        except subprocess.TimeoutExpired:
            return "[error] Search timed out after 30 seconds."
        except FileNotFoundError:
            return "[error] ripgrep (rg) is not installed."

    return search
