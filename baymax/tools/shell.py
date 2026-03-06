"""Sandboxed shell tool — runs in project root, output scrubbed against blacklist."""

from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool

from baymax.permissions import filter_blacklisted_output


def create_shell_tool(project_root: str):
    root = Path(project_root).resolve()

    @tool
    def shell(command: str) -> str:
        """Run a shell command in the project root directory. Returns stdout + stderr."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=120,
            )
            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                output += f"\n[stderr]\n{result.stderr}"
            output += f"\n[exit_code: {result.returncode}]"
            output = output.strip()
            return filter_blacklisted_output(output, str(root))
        except subprocess.TimeoutExpired:
            return "[error] Command timed out after 120 seconds."

    return shell
