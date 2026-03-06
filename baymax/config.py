"""Load YAML config, prompt files, and environment variables."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


_BAYMAX_ROOT = Path(__file__).resolve().parent.parent

# Load .env from Baymax root, then from parent project root (parent takes precedence)
load_dotenv(_BAYMAX_ROOT / ".env")
load_dotenv(_BAYMAX_ROOT / ".." / ".env", override=True)


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
    """Resolve a config file with fallback to .default.yaml.

    Tries ``config/<name>.yaml`` first (user-created, gitignored),
    then ``config/<name>.default.yaml`` (tracked).
    """
    user = _BAYMAX_ROOT / "config" / f"{name}.yaml"
    if user.exists():
        return user
    default = _BAYMAX_ROOT / "config" / f"{name}.default.yaml"
    if default.exists():
        return default
    return user  # will raise FileNotFoundError with a clear path


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
        preset_path = _BAYMAX_ROOT / "prompts" / "samples" / preset / f"{name}.md"
        if preset_path.exists():
            path = preset_path

    if path is None:
        path = _BAYMAX_ROOT / "prompts" / f"{name}.md"

    text = path.read_text()

    for var, display in _role_template_vars().items():
        text = text.replace(f"{{{var}}}", display)

    return text


def load_nodes_config() -> dict[str, Any]:
    return load_yaml(_config_path("nodes"))


def load_project_config() -> dict[str, Any]:
    return load_yaml(_config_path("project"))


def get_project_root() -> Path:
    """Resolve the target project root relative to Baymax's own directory."""
    cfg = load_project_config()
    raw = cfg.get("root_dir", "..")
    return (_BAYMAX_ROOT / raw).resolve()


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
