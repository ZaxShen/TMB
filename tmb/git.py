"""Git helpers — TMB's internal version control for user projects.

Silent, always-on. Provides rollback snapshots and structured post-completion commits.
All functions are safe: catch subprocess errors, log warnings, never raise.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("tmb.git")

_GITIGNORE_DEFAULTS = """\
# TMB auto-generated
.env
.env.*
__pycache__/
*.pyc
.tmb/
node_modules/
.DS_Store
*.egg-info/
dist/
build/
"""


def has_git_binary() -> bool:
    """Return True if the git binary is available on PATH."""
    return shutil.which("git") is not None


def ensure_repo(root: Path) -> bool:
    """Ensure `root` is a git repository, initialising one if necessary.

    Steps:
    1. Bail out early if git is not installed.
    2. If already inside a git repo, return True immediately.
    3. Run ``git init`` in `root`.
    4. Create a default ``.gitignore`` if one does not exist.
    5. Set ``user.name`` / ``user.email`` if not already configured.

    Returns True on success, False on any error.
    """
    try:
        if not has_git_binary():
            logger.warning("ensure_repo: git binary not found on PATH")
            return False

        # Check if already inside a git repo.
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Already inside a git repo — leave it alone.
            return True

        # Initialise a new repo.
        init = subprocess.run(
            ["git", "init"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if init.returncode != 0:
            logger.warning(
                "ensure_repo: git init failed in %s: %s", root, init.stderr.strip()
            )
            return False

        # Write a default .gitignore if one doesn't exist yet.
        gitignore = root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(_GITIGNORE_DEFAULTS, encoding="utf-8")

        # Configure repo-local user identity (needed to commit).
        name_check = subprocess.run(
            ["git", "config", "user.name"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if name_check.returncode != 0:
            subprocess.run(
                ["git", "config", "user.name", "TMB"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            subprocess.run(
                ["git", "config", "user.email", "tmb@local"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=5,
            )

        return True

    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure_repo: unexpected error for %s: %s", root, exc)
        return False


def snapshot(root: Path, message: str) -> str | None:
    """Stage all changes and create a commit in `root`.

    Returns the short commit hash, or None if there was nothing to commit or
    an error occurred.
    """
    try:
        if not has_git_binary():
            return None

        # Stage everything.
        add = subprocess.run(
            ["git", "add", "-A"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if add.returncode != 0:
            logger.warning(
                "snapshot: git add -A failed in %s: %s", root, add.stderr.strip()
            )
            return None

        # Check if there is anything staged.
        diff_check = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if diff_check.returncode == 0:
            # Nothing staged — nothing to commit.
            return None

        # Commit.
        commit = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=15,
        )
        if commit.returncode != 0:
            logger.warning(
                "snapshot: git commit failed in %s: %s", root, commit.stderr.strip()
            )
            return None

        # Retrieve the short hash.
        rev = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if rev.returncode != 0:
            logger.warning(
                "snapshot: git rev-parse failed in %s: %s", root, rev.stderr.strip()
            )
            return None

        return rev.stdout.strip()

    except Exception as exc:  # noqa: BLE001
        logger.warning("snapshot: unexpected error for %s: %s", root, exc)
        return None


def get_diff_summary(root: Path) -> list[dict]:
    """Return a list of changed-file dicts from ``git status --porcelain``.

    Each dict has the shape ``{"path": "rel/path", "status": "<label>"}``.
    Status labels: ``added``, ``modified``, ``deleted``, ``renamed``.

    Returns an empty list on any error.
    """
    try:
        if not has_git_binary():
            return []

        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning(
                "get_diff_summary: git status failed in %s: %s",
                root,
                result.stderr.strip(),
            )
            return []

        entries: list[dict] = []
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            code = line[:2]
            file_part = line[3:]

            if code in ("A ", "??"):
                status = "added"
            elif code in ("M ", " M", "MM"):
                status = "modified"
            elif code in ("D ", " D"):
                status = "deleted"
            elif code.startswith("R"):
                status = "renamed"
                # Porcelain v1 rename: "old -> new" — take the new path.
                if " -> " in file_part:
                    file_part = file_part.split(" -> ", 1)[1]
            else:
                # Treat anything else (e.g. "C", "U") as modified.
                status = "modified"

            entries.append({"path": file_part.strip(), "status": status})

        return entries

    except Exception as exc:  # noqa: BLE001
        logger.warning("get_diff_summary: unexpected error for %s: %s", root, exc)
        return []


def build_commit_message(
    issue_id: int,
    objective: str,
    tasks: list[dict],
    diff_summary: list[dict],
) -> str:
    """Build a structured commit message for a completed TMB issue.

    Args:
        issue_id:     The TMB issue number.
        objective:    Short description of the issue objective (truncated to 80 chars).
        tasks:        List of task dicts, each with at least ``branch_id`` and ``title``.
        diff_summary: Output of :func:`get_diff_summary`.

    Returns a multi-line commit message string.
    """
    header = f"tmb: Issue #{issue_id} \u2014 {objective[:80]}"
    parts = [header]

    if tasks:
        parts.append("")
        parts.append("Tasks completed:")
        for task in tasks:
            parts.append(f"- [{task['branch_id']}] {task['title']}")

    if diff_summary:
        parts.append("")
        parts.append("Files changed:")
        for entry in diff_summary:
            parts.append(f"- {entry['path']} ({entry['status']})")

    return "\n".join(parts)
