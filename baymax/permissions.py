"""Permission enforcement for agent file access.

Four layers:

1. Docs write allowlist — agents may only write specific files inside
   the baymax-docs/ directory (bypassed in evolve mode).

2. Project blacklist — agents can NEVER access paths matching patterns
   in config/project.yaml → blacklist[]. Applies to all nodes.
   In evolve mode, the ``Baymax/**`` pattern is lifted while all other
   patterns (secrets, .env, *.pem, etc.) remain enforced.

3. Node-level access — certain docs are restricted to specific nodes.
   High-level docs (GOALS, DISCUSSION, BLUEPRINT, FLOWCHART) are planner-only.
   EXECUTION.md is readable by executor. QA_PLAN.md is readable by validator.

4. Evolve context — a ``contextvars``-based toggle that temporarily lifts
   the Baymax/** blacklist and write allowlist so the Planner can modify
   any Baymax source file during a guarded self-evolution flow.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from fnmatch import fnmatch
from pathlib import Path

from baymax.config import load_project_config
from baymax.paths import BAYMAX_ROOT, docs_dir


# ── Evolve-mode context ─────────────────────────────────────

_evolve_mode = contextvars.ContextVar("evolve_mode", default=False)


@contextmanager
def evolve_context():
    """Temporarily lift the Baymax/** blacklist and write allowlist
    for a guarded self-evolution session."""
    token = _evolve_mode.set(True)
    try:
        yield
    finally:
        _evolve_mode.reset(token)


def is_evolve_mode() -> bool:
    return _evolve_mode.get()


# ── Docs write allowlist ─────────────────────────────────────

_WRITABLE_DOC_NAMES = {
    "DISCUSSION.md",
    "BLUEPRINT.md",
    "FLOWCHART.md",
    "EXECUTION.md",
    "QA_PLAN.md",
    "EVOLUTION.md",
}


def assert_baymax_write(path: Path):
    """Raise if the path is not in the docs write allowlist.
    Bypassed entirely when evolve mode is active."""
    if _evolve_mode.get():
        return
    resolved = path.resolve()
    dd = docs_dir().resolve()
    if resolved.parent == dd and resolved.name in _WRITABLE_DOC_NAMES:
        return
    raise PermissionError(
        f"Write blocked: {path} is not in the docs write allowlist. "
        f"Allowed: {', '.join(_WRITABLE_DOC_NAMES)}"
    )


# ── Node-level access control ──────────────────────────────

_NODE_RESTRICTED_NAMES: dict[str, set[str]] = {
    "GOALS.md": {"planner", "gatekeeper"},
    "DISCUSSION.md": {"planner"},
    "BLUEPRINT.md": {"planner", "owner"},
    "FLOWCHART.md": {"planner", "owner"},
    "EXECUTION.md": {"planner", "executor"},
    "QA_PLAN.md": {"planner"},
    "EVOLUTION.md": {"planner"},
}


def assert_node_access(file_path: str, node_name: str):
    """Raise if this node is not allowed to access the file.
    Only checks node-restricted doc names — unrestricted paths pass through.
    Bypassed entirely when evolve mode is active."""
    if _evolve_mode.get():
        return
    fname = Path(file_path).name
    allowed_nodes = _NODE_RESTRICTED_NAMES.get(fname)
    if allowed_nodes is not None:
        if node_name not in allowed_nodes:
            raise PermissionError(
                f"Access denied: '{file_path}' is restricted to {allowed_nodes}. "
                f"Node '{node_name}' cannot access this file."
            )


# ── Project blacklist ───────────────────────────────────────

_BAYMAX_BLACKLIST_PATTERN = "Baymax/**"


def _load_blacklist() -> list[str]:
    cfg = load_project_config()
    patterns = cfg.get("blacklist", [])
    if _evolve_mode.get():
        patterns = [p for p in patterns if p != _BAYMAX_BLACKLIST_PATTERN]
    return patterns


def is_blacklisted(file_path: str) -> bool:
    """Check if a relative path matches any blacklist pattern."""
    patterns = _load_blacklist()
    normalized = file_path.lstrip("./")
    for pattern in patterns:
        if fnmatch(normalized, pattern):
            return True
        if fnmatch(Path(normalized).name, pattern):
            return True
    return False


def assert_not_blacklisted(file_path: str):
    """Raise if the path matches a blacklist pattern."""
    if is_blacklisted(file_path):
        raise PermissionError(
            f"Access blocked: '{file_path}' matches a blacklist pattern. "
            f"This file is protected and cannot be accessed by agents."
        )


def _extract_paths(line: str) -> list[str]:
    """Extract plausible file paths from a line of shell output."""
    candidates = []
    for token in line.split():
        cleaned = token.strip("'\"(),;:")
        if "/" in cleaned or cleaned.startswith("."):
            candidates.append(cleaned)
    return candidates


def filter_blacklisted_output(text: str, project_root: str) -> str:
    """Scrub lines that reference blacklisted file paths from shell/search output."""
    if not text:
        return text
    patterns = _load_blacklist()
    if not patterns:
        return text

    lines = text.splitlines()
    filtered = []
    for line in lines:
        is_blocked = False
        paths = _extract_paths(line)
        for path_str in paths:
            for pattern in patterns:
                if fnmatch(path_str, pattern) or fnmatch(Path(path_str).name, pattern):
                    is_blocked = True
                    break
            if is_blocked:
                break
        if is_blocked:
            filtered.append("[REDACTED — blacklisted path]")
        else:
            filtered.append(line)
    return "\n".join(filtered)
