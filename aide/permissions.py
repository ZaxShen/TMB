"""Permission enforcement for agent file access.

Four layers:

1. AIDE write allowlist — agents may only write specific doc files
   inside the AIDE directory (bypassed in evolve mode).

2. Project blacklist — agents can NEVER access paths matching patterns
   in config/project.yaml → blacklist[]. Applies to all nodes.
   In evolve mode, the ``AIDE/**`` pattern is lifted while all other
   patterns (secrets, .env, *.pem, etc.) remain enforced.

3. Node-level access — certain AIDE docs are restricted to specific nodes.
   High-level docs (GOALS, DISCUSSION, BLUEPRINT, FLOWCHART) are architect-only.
   EXECUTION.md is readable by executor. QA_PLAN.md is readable by validator.

4. Evolve context — a ``contextvars``-based toggle that temporarily lifts
   the AIDE/** blacklist and write allowlist so the Architect can modify
   any AIDE source file during a guarded self-evolution flow.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from fnmatch import fnmatch
from pathlib import Path

from aide.config import _AIDE_ROOT, load_project_config


# ── Evolve-mode context ─────────────────────────────────────

_evolve_mode = contextvars.ContextVar("evolve_mode", default=False)


@contextmanager
def evolve_context():
    """Temporarily lift the AIDE/** blacklist and write allowlist
    for a guarded self-evolution session."""
    token = _evolve_mode.set(True)
    try:
        yield
    finally:
        _evolve_mode.reset(token)


def is_evolve_mode() -> bool:
    return _evolve_mode.get()


# ── AIDE internal write allowlist ───────────────────────────

_AIDE_WRITABLE = {
    _AIDE_ROOT / "doc" / "DISCUSSION.md",
    _AIDE_ROOT / "doc" / "BLUEPRINT.md",
    _AIDE_ROOT / "doc" / "FLOWCHART.md",
    _AIDE_ROOT / "doc" / "EXECUTION.md",
    _AIDE_ROOT / "doc" / "QA_PLAN.md",
    _AIDE_ROOT / "doc" / "EVOLUTION.md",
}


def assert_aide_write(path: Path):
    """Raise if the path is not in the AIDE write allowlist.
    Bypassed entirely when evolve mode is active."""
    if _evolve_mode.get():
        return
    resolved = path.resolve()
    if resolved not in _AIDE_WRITABLE:
        raise PermissionError(
            f"Write blocked: {path} is not in the AIDE write allowlist. "
            f"Allowed: {', '.join(str(p.relative_to(_AIDE_ROOT)) for p in _AIDE_WRITABLE)}"
        )


# ── Node-level access control ──────────────────────────────

_NODE_RESTRICTED: dict[str, set[str]] = {
    "AIDE/doc/GOALS.md": {"architect", "gatekeeper"},
    "AIDE/doc/DISCUSSION.md": {"architect"},
    "AIDE/doc/BLUEPRINT.md": {"architect", "cto"},
    "AIDE/doc/FLOWCHART.md": {"architect", "cto"},
    "AIDE/doc/EXECUTION.md": {"architect", "executor"},
    "AIDE/doc/QA_PLAN.md": {"architect", "validator"},
    "AIDE/doc/EVOLUTION.md": {"architect"},
}


def assert_node_access(file_path: str, node_name: str):
    """Raise if this node is not allowed to access the file.
    Only checks node-restricted paths — unrestricted paths pass through.
    Bypassed entirely when evolve mode is active."""
    if _evolve_mode.get():
        return
    normalized = file_path.lstrip("./")
    for restricted_path, allowed_nodes in _NODE_RESTRICTED.items():
        if normalized == restricted_path or normalized.endswith(restricted_path):
            if node_name not in allowed_nodes:
                raise PermissionError(
                    f"Access denied: '{file_path}' is restricted to {allowed_nodes}. "
                    f"Node '{node_name}' cannot access this file."
                )
            return


# ── Project blacklist ───────────────────────────────────────

_AIDE_BLACKLIST_PATTERN = "AIDE/**"


def _load_blacklist() -> list[str]:
    cfg = load_project_config()
    patterns = cfg.get("blacklist", [])
    if _evolve_mode.get():
        patterns = [p for p in patterns if p != _AIDE_BLACKLIST_PATTERN]
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
