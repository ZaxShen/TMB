"""Gatekeeper node — deterministic context gatherer. No LLM, just code.

Scans the project directory to build a context snapshot so downstream
agents know what they're working with.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aide.config import load_project_config, get_project_root
from aide.state import AgentState

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
        result = subprocess.run(
            [
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
            ],
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
    for name in _KEY_FILES:
        path = root / name
        if path.is_file():
            try:
                content = path.read_text()[:_MAX_FILE_PREVIEW]
                sections.append(f"--- {name} ---\n{content}")
            except Exception:
                continue
    return "\n\n".join(sections) if sections else "(no key files found)"


def gatekeeper(state: AgentState) -> dict:
    project_cfg = load_project_config()
    root = get_project_root()

    print("[GATEKEEPER] Scanning project...")

    tree = _get_tree(root)
    key_files = _read_key_files(root)

    context = (
        f"## Project: {project_cfg.get('name', 'unknown')}\n"
        f"## Root: {root}\n\n"
        f"### Directory structure\n```\n{tree}\n```\n\n"
        f"### Key files\n{key_files}\n"
    )

    print(f"[GATEKEEPER] Scanned {len(tree.splitlines())} paths at {root}")

    return {"project_context": context}
