"""Sandboxed shell tool — runs in project root, output scrubbed against blacklist.

Security layers:
  1. Command deny-list — blocks obviously destructive patterns
  2. Blacklisted path pre-check — blocks commands referencing protected files
  3. Output scrubbing — redacts blacklisted paths from stdout/stderr
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from langchain_core.tools import tool

from tmb.permissions import filter_blacklisted_output, is_blacklisted


# ── Command deny-list ────────────────────────────────────────

_DENY_PATTERNS: list[re.Pattern] = [
    re.compile(p)
    for p in [
        r"\brm\s+-rf\s+/",              # rm -rf /
        r"\brm\s+-rf\s+~",              # rm -rf ~
        r"\bcurl\b.*\|\s*\bbash\b",     # curl | bash
        r"\bwget\b.*\|\s*\bbash\b",     # wget | bash
        r"\bchmod\s+777\b",             # chmod 777
        r"\bmkfs\b",                     # mkfs
        r"\bdd\s+if=",                   # dd
        r":\(\)\s*\{",                   # fork bomb :(){ :|:& };:
        r"\bsudo\b",                     # sudo
        r"\bsu\s+-",                     # su -
    ]
]


def _is_denied(command: str) -> str | None:
    """Return a reason string if the command matches a deny pattern, else None."""
    for pattern in _DENY_PATTERNS:
        if pattern.search(command):
            return f"Command blocked by deny-list: matches {pattern.pattern!r}"
    return None


def _references_blacklisted_path(command: str) -> str | None:
    """Check if the command explicitly references a blacklisted file path."""
    for token in command.split():
        cleaned = token.strip("'\"`;|&>< ")
        if cleaned and is_blacklisted(cleaned):
            return f"Command references blacklisted path: {cleaned}"
    return None


def create_shell_tool(project_root: str):
    root = Path(project_root).resolve()

    @tool
    def shell(command: str) -> str:
        """Run a shell command in the project root directory. Returns stdout + stderr."""
        # Security: deny-list check
        deny_reason = _is_denied(command)
        if deny_reason:
            return f"[blocked] {deny_reason}"

        # Security: blacklisted path pre-check
        path_reason = _references_blacklisted_path(command)
        if path_reason:
            return f"[blocked] {path_reason}"

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
