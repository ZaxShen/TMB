"""Gatekeeper node — deterministic context gatherer. No LLM, just code.

Scans the project directory to build a context snapshot so downstream
agents know what they're working with.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from tmb.config import load_project_config, get_project_root
from tmb.state import AgentState

_KEY_FILES = [
    "README.md",
    "readme.md",
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    ".env.example",
]

_MAX_FILE_PREVIEW = 3000


def _get_tree(root: Path, max_depth: int = 3) -> str:
    try:
        cmd = [
            "find", str(root),
            "-maxdepth", str(max_depth),
            "-not", "-path", "*/.git/*",
            "-not", "-path", "*/.git",
            "-not", "-path", "*/__pycache__/*",
            "-not", "-path", "*/.venv/*",
            "-not", "-path", "*/node_modules/*",
            "-not", "-path", "*/.mypy_cache/*",
            "-not", "-name", "*.pyc",
            "-not", "-name", "uv.lock",
        ]

        # Add user-configured exclude patterns from project.yaml
        exclude_patterns = load_project_config().get("exclude", [])
        for pattern in exclude_patterns:
            cmd.extend(["-not", "-path", f"*/{pattern}"])

        result = subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=10,
        )
        lines = sorted(result.stdout.strip().splitlines())
        prefix = str(root)
        return "\n".join(
            line.replace(prefix, ".") for line in lines if line.strip()
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "(could not scan directory)"


def _read_key_files(root: Path) -> str:
    sections = []
    seen: set[str] = set()
    for name in _KEY_FILES:
        path = root / name
        # Deduplicate on case-insensitive filesystems (macOS)
        key = name.lower()
        if key in seen:
            continue
        if path.is_file():
            seen.add(key)
            try:
                content = path.read_text()[:_MAX_FILE_PREVIEW]
                sections.append(f"--- {name} ---\n{content}")
            except Exception:
                continue
    return "\n\n".join(sections) if sections else "(no key files found)"


def gatekeeper(state: AgentState) -> dict:
    project_cfg = load_project_config()
    root = get_project_root()

    print("[GATEKEEPER] 🔍 Scanning project...")

    tree = _get_tree(root)
    key_files = _read_key_files(root)

    context = (
        f"## Project: {project_cfg.get('name', 'unknown')}\n"
        f"## Root: {root}\n\n"
        f"### Directory structure\n```\n{tree}\n```\n\n"
        f"### Key files\n{key_files}\n"
    )

    from tmb.store import Store
    from tmb.scanner import build_project_context_from_scan

    store = Store()
    if store.file_registry_count() > 0:
        scan_ctx = build_project_context_from_scan(store)
        if scan_ctx:
            context += f"\n{scan_ctx}\n"
            print(f"[GATEKEEPER] 📊 Enriched with scan data ({store.file_registry_count()} files in registry)")

    print(f"[GATEKEEPER] ✅ Scanned {len(tree.splitlines())} paths at {root}")

    return {"project_context": context}
