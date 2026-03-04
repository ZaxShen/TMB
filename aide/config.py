"""Load YAML config, prompt files, and environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


_AIDE_ROOT = Path(__file__).resolve().parent.parent

# Load .env from AIDE root, then from parent project root (parent takes precedence)
load_dotenv(_AIDE_ROOT / ".env")
load_dotenv(_AIDE_ROOT / ".." / ".env", override=True)


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f)


def load_prompt(name: str) -> str:
    path = _AIDE_ROOT / "prompts" / f"{name}.md"
    return path.read_text()


def load_nodes_config() -> dict[str, Any]:
    return load_yaml(_AIDE_ROOT / "config" / "nodes.yaml")


def load_project_config() -> dict[str, Any]:
    return load_yaml(_AIDE_ROOT / "config" / "project.yaml")


def get_project_root() -> Path:
    """Resolve the target project root relative to AIDE's own directory."""
    cfg = load_project_config()
    raw = cfg.get("root_dir", "..")
    return (_AIDE_ROOT / raw).resolve()


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
