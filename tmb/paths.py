"""Centralized path registry — single source of truth for all file locations.

Three layers:
  1. Framework paths  — inside TMB/, resolved from __file__ (immutable)
  2. Project defaults — directory names for user-facing / runtime locations
  3. Config overrides — users customize via .tmb/config/project.yaml → paths:
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

TMB_ROOT = Path(__file__).resolve().parent.parent

# ── Data file resolution ──────────────────────────────────
# In PyPI install: data files are at tmb/_data/ (via hatchling force-include)
# In dev/editable install: data files are at TMB/ root (parent of tmb/)
_PKG_DIR = Path(__file__).resolve().parent
_DATA_DIR = _PKG_DIR / "_data"
if not _DATA_DIR.is_dir():
    _DATA_DIR = _PKG_DIR.parent  # Development layout

# ── Layer 1: Framework paths (immutable, inside TMB/) ─────

PROMPTS_DIR     = _DATA_DIR / "prompts"
SYSTEM_PROMPTS_DIR = PROMPTS_DIR / "system"
SAMPLES_DIR     = PROMPTS_DIR / "samples"
DEFAULT_CFG_DIR = _DATA_DIR / "config"
SEED_SKILLS_DIR = _DATA_DIR / "skills"

# ── Layer 2: Defaults for project-level directory names ──────

_DEFAULTS = {
    "docs_dir":    "bro",
    "runtime_dir": ".tmb",
    "db_name":     "tmb.db",
}


# ── Layer 3: Runtime resolution (lazy — config must load first) ──

def _project_root() -> Path:
    from tmb.config import get_project_root
    return get_project_root()


def _get_path_setting(key: str) -> str:
    from tmb.config import load_project_config
    cfg = load_project_config()
    return (cfg.get("paths") or {}).get(key, _DEFAULTS[key])


def docs_dir() -> Path:
    """User interaction zone: GOALS.md, DISCUSSION.md, BLUEPRINT.md, etc."""
    return _project_root() / _get_path_setting("docs_dir")


def runtime_dir() -> Path:
    """Hidden runtime state: DB, user config overrides, agent-created skills."""
    return _project_root() / _get_path_setting("runtime_dir")


def db_path() -> Path:
    return runtime_dir() / _get_path_setting("db_name")


def user_cfg_dir() -> Path:
    return runtime_dir() / "config"


def user_skills_dir() -> Path:
    return runtime_dir() / "skills"


def user_prompts_dir() -> Path:
    """Auto-generated prompts tailored to the project's purpose."""
    return runtime_dir() / "prompts"


def ensure_dirs():
    """Create project-level directories on first run."""
    for d in [docs_dir(), runtime_dir(), user_cfg_dir(), user_skills_dir(), user_prompts_dir()]:
        d.mkdir(parents=True, exist_ok=True)
