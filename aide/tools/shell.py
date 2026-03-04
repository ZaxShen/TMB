"""Sandboxed shell tool — all commands run within the project root."""

from __future__ import annotations

import subprocess
from pathlib import Path

from langchain_core.tools import tool


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
            return output.strip()
        except subprocess.TimeoutExpired:
            return "[error] Command timed out after 120 seconds."

    return shell
