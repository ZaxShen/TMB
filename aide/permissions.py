"""Permission enforcement for agent file access.

Three layers:

1. AIDE write allowlist — agents may only write doc/DISCUSSION.md and
   doc/BLUEPRINT.md inside the AIDE directory.

2. Project blacklist — agents can NEVER access paths matching patterns
   in config/project.yaml → blacklist[]. Applies to all nodes.

3. Node-level access — certain AIDE docs are restricted to specific nodes.
   GOALS.md and DISCUSSION.md are architect-only. Executors and validators
   get their task info from the DB, never from high-level docs.
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from aide.config import _AIDE_ROOT, load_project_config


# ── AIDE internal write allowlist ───────────────────────────

_AIDE_WRITABLE = {
    _AIDE_ROOT / "doc" / "DISCUSSION.md",
    _AIDE_ROOT / "doc" / "BLUEPRINT.md",
}


def assert_aide_write(path: Path):
    """Raise if the path is not in the AIDE write allowlist."""
    resolved = path.resolve()
    if resolved not in _AIDE_WRITABLE:
        raise PermissionError(
            f"Write blocked: {path} is not in the AIDE write allowlist. "
            f"Allowed: {', '.join(str(p.relative_to(_AIDE_ROOT)) for p in _AIDE_WRITABLE)}"
        )


# ── Node-level access control ──────────────────────────────

# Paths inside the project that only specific nodes may access.
# If a path matches, only the listed nodes can read it.
# Everyone else is blocked.
_NODE_RESTRICTED: dict[str, set[str]] = {
    "AIDE/doc/GOALS.md": {"architect", "gatekeeper"},
    "AIDE/doc/DISCUSSION.md": {"architect"},
    "AIDE/doc/BLUEPRINT.md": {"architect", "cto"},
}


def assert_node_access(file_path: str, node_name: str):
    """Raise if this node is not allowed to access the file.
    Only checks node-restricted paths — unrestricted paths pass through."""
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

def _load_blacklist() -> list[str]:
    cfg = load_project_config()
    return cfg.get("blacklist", [])


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
