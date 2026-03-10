"""Load YAML config, prompt files, and environment variables."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from baymax.paths import BAYMAX_ROOT, DEFAULT_CFG_DIR, PROMPTS_DIR

_BAYMAX_ROOT = BAYMAX_ROOT  # backward compat alias

# Load .env: project root CWD wins over Baymax/
load_dotenv(BAYMAX_ROOT / ".env")           # legacy fallback
load_dotenv(BAYMAX_ROOT / ".." / ".env", override=True)
_cwd_env = Path.cwd() / ".env"
if _cwd_env.exists() and _cwd_env.resolve() != (BAYMAX_ROOT / ".env").resolve():
    load_dotenv(_cwd_env, override=True)


_DEFAULT_ROLE_NAMES = {
    "owner": "Project Owner",
    "planner": "Planner",
    "executor": "Executor",
    "validator": "Validator",
}


def get_role_name(key: str) -> str:
    """Return the display name for a role key (e.g. 'planner' → 'Architect').

    Reads ``roles:`` from project.yaml. Falls back to generic defaults.
    """
    cfg = load_project_config()
    roles = cfg.get("roles") or {}
    return roles.get(key, _DEFAULT_ROLE_NAMES.get(key, key.title()))


def _role_template_vars() -> dict[str, str]:
    """Build template variables for prompt substitution."""
    return {f"role_{k}": get_role_name(k) for k in _DEFAULT_ROLE_NAMES}


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _config_path(name: str) -> Path:
    """Resolve a config file with three-layer fallback.

    1. <project>/.baymax/config/<name>.yaml   (project-level user overrides)
    2. Baymax/config/<name>.yaml              (legacy overrides inside framework)
    3. Baymax/config/<name>.default.yaml      (tracked defaults)

    Uses _detect_project_root() instead of paths.user_cfg_dir() to avoid
    circular dependency (paths.py → config.py → paths.py).
    """
    project_override = _detect_project_root() / ".baymax" / "config" / f"{name}.yaml"
    if project_override.exists():
        return project_override
    user = DEFAULT_CFG_DIR / f"{name}.yaml"
    if user.exists():
        return user
    default = DEFAULT_CFG_DIR / f"{name}.default.yaml"
    if default.exists():
        return default
    return user


def load_prompt(name: str) -> str:
    """Load a prompt file with preset and template variable support.

    Resolution order:
      1. prompts/samples/<preset>/<name>.md  (if roles.preset is set)
      2. prompts/<name>.md  (default)

    Template variables like ``{role_planner}`` are replaced with display names
    from project.yaml → roles.
    """
    cfg = load_project_config()
    roles = cfg.get("roles") or {}
    preset = roles.get("preset")

    path = None
    if preset:
        preset_path = PROMPTS_DIR / "samples" / preset / f"{name}.md"
        if preset_path.exists():
            path = preset_path

    if path is None:
        path = PROMPTS_DIR / f"{name}.md"

    text = path.read_text()

    for var, display in _role_template_vars().items():
        text = text.replace(f"{{{var}}}", display)

    return text


def load_nodes_config() -> dict[str, Any]:
    return load_yaml(_config_path("nodes"))


def load_project_config() -> dict[str, Any]:
    return load_yaml(_config_path("project"))


def _detect_project_root() -> Path:
    """CWD-based project root detection — no config dependency, no recursion."""
    cwd = Path.cwd().resolve()
    baymax_resolved = BAYMAX_ROOT.resolve()
    if cwd == baymax_resolved or str(cwd).startswith(str(baymax_resolved) + os.sep):
        return baymax_resolved.parent
    return cwd


def get_project_root() -> Path:
    """Resolve the target project root.

    Resolution order:
      1. ``root_dir`` in project.yaml (resolved relative to BAYMAX_ROOT)
      2. Auto-detect from CWD via _detect_project_root()
    """
    cfg = load_project_config()
    raw = cfg.get("root_dir", "")
    if raw:
        return (BAYMAX_ROOT / raw).resolve()
    return _detect_project_root()


def _resolve_env_vars(value: str) -> str:
    """Replace ${VAR} references with environment variable values."""
    def _sub(m):
        return os.environ.get(m.group(1), "")
    return re.sub(r"\$\{(\w+)\}", _sub, value)


def load_mcp_config() -> dict[str, Any]:
    """Load MCP config with ${VAR} resolution on env values.

    Tries config/mcp.yaml → config/mcp.default.yaml → empty.
    """
    path = _config_path("mcp")
    if not path.exists():
        return {"servers": {}}
    raw = load_yaml(path)
    servers = raw.get("servers") or {}
    for _name, cfg in servers.items():
        env = cfg.get("env") or {}
        cfg["env"] = {k: _resolve_env_vars(str(v)) for k, v in env.items()}
    return {"servers": servers}


def get_llm(node_name: str):
    """Instantiate the LLM for a given node based on config/nodes.yaml."""
    cfg = load_nodes_config()[node_name]["model"]
    provider = cfg["provider"]
    model_name = cfg["name"]
    temperature = cfg.get("temperature", 0)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(model=model_name, temperature=temperature)
    elif provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_name, temperature=temperature)
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def extract_token_usage(response) -> dict:
    """Extract token counts from an AIMessage, normalized across providers."""
    meta = getattr(response, "response_metadata", {}) or {}
    usage = meta.get("usage", {})
    if usage:
        return {"input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0)}
    usage = meta.get("token_usage", {})
    if usage:
        return {"input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0)}
    return {"input_tokens": 0, "output_tokens": 0}
