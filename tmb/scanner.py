"""Project scanner — walk project tree, parse git history, register context in DB."""

from __future__ import annotations

import hashlib
import subprocess
from fnmatch import fnmatch
from pathlib import Path

from tmb.store import Store

_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox",
    "dist", "build", ".eggs", ".tmb", "bro",
}

_SKIP_FILES = {"uv.lock", ".DS_Store", "Thumbs.db"}

_TYPE_MAP = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "javascript", ".tsx": "typescript",
    ".rs": "rust", ".go": "go", ".java": "java",
    ".rb": "ruby", ".php": "php", ".c": "c", ".cpp": "cpp",
    ".h": "c-header", ".hpp": "cpp-header", ".cs": "csharp",
    ".swift": "swift", ".kt": "kotlin",
    ".md": "markdown", ".rst": "rst", ".txt": "text",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".ini": "ini", ".cfg": "config",
    ".html": "html", ".css": "css", ".scss": "scss",
    ".sql": "sql", ".sh": "shell", ".bash": "shell",
    ".dockerfile": "docker", ".csv": "csv", ".xml": "xml",
}

_KEY_DOC_FILES = [
    "README.md", "readme.md", "README.rst",
    "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
    "Makefile", "Dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "requirements.txt", "setup.py", "setup.cfg",
    ".env.example", "tsconfig.json", "webpack.config.js",
    "CHANGELOG.md", "CONTRIBUTING.md", "LICENSE",
]

_MAX_DOC_PREVIEW = 4000


def _file_hash(path: Path) -> str:
    """Quick content hash (first 64KB)."""
    try:
        data = path.read_bytes()[:65536]
        return hashlib.sha256(data).hexdigest()[:16]
    except Exception:
        return ""


def _detect_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if path.name == "Dockerfile":
        return "docker"
    if path.name == "Makefile":
        return "makefile"
    return _TYPE_MAP.get(suffix, "unknown")


def _should_skip(rel: str, blacklist: list[str]) -> bool:
    for pattern in blacklist:
        if fnmatch(rel, pattern) or fnmatch(Path(rel).name, pattern):
            return True
    return False


def _git_log_summary(project_root: Path, max_commits: int = 50) -> str:
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={max_commits}",
             "--pretty=format:%h|%an|%ar|%s"],
            cwd=str(project_root), capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _git_branch_info(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "branch", "-a", "--no-color"],
            cwd=str(project_root), capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _git_contributors(project_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "shortlog", "-sn", "--all"],
            cwd=str(project_root), capture_output=True, text=True, timeout=15,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def scan_project(project_root: Path, store: Store, blacklist: list[str] | None = None) -> dict:
    """Walk the project, register files, parse git, and store context. Returns summary stats."""
    if blacklist is None:
        from tmb.config import load_project_config
        cfg = load_project_config()
        blacklist = cfg.get("blacklist", [])

    root = project_root.resolve()
    file_count = 0
    type_counts: dict[str, int] = {}
    total_size = 0

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue

        rel_parts = path.relative_to(root).parts
        if any(part in _SKIP_DIRS for part in rel_parts):
            continue
        if path.name in _SKIP_FILES:
            continue

        rel = str(path.relative_to(root))
        if _should_skip(rel, blacklist):
            continue

        ftype = _detect_type(path)
        size = path.stat().st_size
        fhash = _file_hash(path)

        store.upsert_file(rel, file_type=ftype, size_bytes=size, last_hash=fhash)
        file_count += 1
        type_counts[ftype] = type_counts.get(ftype, 0) + 1
        total_size += size

    tech_stack = detect_tech_stack(root)
    store.set_project_meta("tech_stack", tech_stack)

    git_log = _git_log_summary(root)
    if git_log:
        store.set_project_meta("git_log_recent", git_log[:8000])

    branches = _git_branch_info(root)
    if branches:
        store.set_project_meta("git_branches", branches[:4000])

    contributors = _git_contributors(root)
    if contributors:
        store.set_project_meta("git_contributors", contributors[:2000])

    doc_previews = read_key_docs(root)
    if doc_previews:
        store.set_project_meta("key_docs", doc_previews[:12000])

    type_summary = ", ".join(f"{v} {k}" for k, v in sorted(type_counts.items(), key=lambda x: -x[1]))
    store.set_project_meta("file_type_summary", type_summary)
    store.set_project_meta("scan_file_count", str(file_count))
    store.set_project_meta("scan_total_bytes", str(total_size))

    return {
        "file_count": file_count,
        "type_counts": type_counts,
        "total_size": total_size,
        "tech_stack": tech_stack,
        "has_git": bool(git_log),
    }


def _is_git_repo(root: Path) -> bool:
    """Check if root is inside a git repository."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(root), capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _git_dirty_files(root: Path) -> set[str]:
    """Return set of rel-paths that git considers dirty or untracked.

    Uses ``git status --porcelain`` which covers:
      - Modified (staged or unstaged)
      - Added / Deleted / Renamed
      - Untracked (??)

    This tells us *which* files need re-hashing; everything else can be
    assumed unchanged since last sync.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            cwd=str(root), capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return set()  # fall back to full walk
        dirty: set[str] = set()
        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue
            # porcelain format: XY <path>  or  XY <old> -> <new>
            entry = line[3:]
            if " -> " in entry:
                # rename: mark both old and new
                old, new = entry.split(" -> ", 1)
                dirty.add(old.strip())
                dirty.add(new.strip())
            else:
                dirty.add(entry.strip())
        return dirty
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()


def _git_tracked_files(root: Path) -> set[str]:
    """Return the full set of git-tracked files via ``git ls-files``.

    Combined with untracked from ``git status``, this gives a complete
    picture of the project tree without a filesystem walk.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=str(root), capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()


def _git_untracked_files(root: Path) -> set[str]:
    """Return only untracked (new) files from git status."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "-uall"],
            cwd=str(root), capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return set()
        untracked: set[str] = set()
        for line in result.stdout.splitlines():
            if line.startswith("??"):
                untracked.add(line[3:].strip())
        return untracked
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return set()


def _filter_rel(rel: str, blacklist: list[str]) -> bool:
    """Return True if this rel-path should be included in the registry."""
    parts = Path(rel).parts
    if any(part in _SKIP_DIRS for part in parts):
        return False
    if Path(rel).name in _SKIP_FILES:
        return False
    if _should_skip(rel, blacklist):
        return False
    return True


def sync_file_registry(project_root: Path, store: Store, blacklist: list[str] | None = None) -> int:
    """Fast file-registry refresh — runs before every workflow.

    **Git projects**: Uses ``git ls-files`` + ``git status --porcelain``
    to avoid a full filesystem walk.  Only dirty/untracked files are
    re-hashed — everything else is assumed unchanged.

    **Non-git projects**: Falls back to a full ``rglob("*")`` walk with
    hash-based diffing (same as before).

    Removes registry entries for files that no longer exist.
    Returns the number of files currently registered.
    """
    if blacklist is None:
        from tmb.config import load_project_config
        cfg = load_project_config()
        blacklist = cfg.get("blacklist", [])

    root = project_root.resolve()
    existing = {f["rel_path"]: f["last_hash"] for f in store.get_all_files()}

    use_git = _is_git_repo(root)

    if use_git:
        seen = _sync_via_git(root, store, existing, blacklist)
    else:
        seen = _sync_via_walk(root, store, existing, blacklist)

    # Remove files that no longer exist on disk
    for rel in existing:
        if rel not in seen:
            store.remove_file(rel)

    return len(seen)


def _sync_via_git(
    root: Path, store: Store,
    existing: dict[str, str], blacklist: list[str],
) -> set[str]:
    """Git-accelerated sync — skip hashing for clean tracked files."""
    tracked = _git_tracked_files(root)
    untracked = _git_untracked_files(root)
    dirty = _git_dirty_files(root)

    # Full project file set = tracked ∪ untracked (filtered)
    all_files = tracked | untracked
    seen: set[str] = set()

    for rel in sorted(all_files):
        if not _filter_rel(rel, blacklist):
            continue
        full = root / rel
        if not full.is_file():
            continue

        seen.add(rel)

        # Only re-hash if dirty/untracked OR not in registry yet
        is_new = rel not in existing
        is_dirty = rel in dirty or rel in untracked
        if not is_new and not is_dirty:
            continue

        fhash = _file_hash(full)
        if not is_new and existing[rel] == fhash:
            continue

        # Classify the change
        if is_new:
            change = "added"
        else:
            change = "modified"

        ftype = _detect_type(full)
        size = full.stat().st_size
        store.upsert_file(rel, file_type=ftype, size_bytes=size,
                          last_hash=fhash, change_type=change)

    return seen


def _sync_via_walk(
    root: Path, store: Store,
    existing: dict[str, str], blacklist: list[str],
) -> set[str]:
    """Filesystem walk fallback for non-git projects."""
    seen: set[str] = set()

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(root))
        if not _filter_rel(rel, blacklist):
            continue

        seen.add(rel)
        fhash = _file_hash(path)

        is_new = rel not in existing
        if not is_new and existing[rel] == fhash:
            continue

        change = "added" if is_new else "modified"
        ftype = _detect_type(path)
        size = path.stat().st_size
        store.upsert_file(rel, file_type=ftype, size_bytes=size,
                          last_hash=fhash, change_type=change)

    return seen


def detect_tech_stack(root: Path) -> str:
    indicators: list[str] = []
    if (root / "pyproject.toml").exists() or (root / "setup.py").exists():
        indicators.append("Python")
    if (root / "requirements.txt").exists():
        indicators.append("Python (pip)")
    if (root / "package.json").exists():
        indicators.append("Node.js")
    if (root / "Cargo.toml").exists():
        indicators.append("Rust")
    if (root / "go.mod").exists():
        indicators.append("Go")
    if (root / "Gemfile").exists():
        indicators.append("Ruby")
    if (root / "pom.xml").exists() or (root / "build.gradle").exists():
        indicators.append("Java/JVM")
    if (root / "Dockerfile").exists():
        indicators.append("Docker")
    if (root / "docker-compose.yml").exists() or (root / "docker-compose.yaml").exists():
        indicators.append("Docker Compose")
    if (root / "tsconfig.json").exists():
        indicators.append("TypeScript")
    return ", ".join(indicators) if indicators else "unknown"


def read_key_docs(root: Path) -> str:
    sections = []
    for name in _KEY_DOC_FILES:
        path = root / name
        if path.is_file():
            try:
                content = path.read_text(errors="replace")[:_MAX_DOC_PREVIEW]
                sections.append(f"--- {name} ---\n{content}")
            except Exception:
                continue
    return "\n\n".join(sections)


def build_project_context_from_scan(store: Store) -> str:
    """Build a context string from previously scanned data for the planner."""
    meta = store.get_all_project_meta()
    if not meta:
        return ""

    parts = ["## Project Scan Context\n"]

    if meta.get("tech_stack"):
        parts.append(f"**Tech stack**: {meta['tech_stack']}")
    if meta.get("scan_file_count"):
        parts.append(f"**Files**: {meta['scan_file_count']} ({_human_bytes(int(meta.get('scan_total_bytes', 0)))})")
    if meta.get("file_type_summary"):
        parts.append(f"**File types**: {meta['file_type_summary']}")

    parts.append("")

    if meta.get("git_contributors"):
        parts.append("### Contributors")
        parts.append(f"```\n{meta['git_contributors']}\n```\n")

    if meta.get("git_branches"):
        parts.append("### Branches")
        parts.append(f"```\n{meta['git_branches']}\n```\n")

    if meta.get("git_log_recent"):
        lines = meta["git_log_recent"].splitlines()[:20]
        parts.append("### Recent commits")
        parts.append(f"```\n" + "\n".join(lines) + "\n```\n")

    # Show recently changed files so the planner knows what's fresh
    changed = store.get_changed_files()
    if changed:
        parts.append("### Recently changed files")
        change_lines = []
        for f in changed[:50]:
            symbol = "+" if f["change_type"] == "added" else "~"
            change_lines.append(f"  {symbol} {f['rel_path']}")
        parts.append("```\n" + "\n".join(change_lines) + "\n```\n")

    all_files = store.get_all_files()
    if all_files:
        tree_lines = [f["rel_path"] for f in all_files[:200]]
        parts.append("### File tree (first 200)")
        parts.append("```\n" + "\n".join(tree_lines) + "\n```\n")

    if meta.get("key_docs"):
        preview = meta["key_docs"][:6000]
        parts.append("### Key documentation")
        parts.append(preview)

    return "\n".join(parts)


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"
