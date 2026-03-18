"""Load YAML config, prompt files, and environment variables."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from tmb.paths import TMB_ROOT, DEFAULT_CFG_DIR, PROMPTS_DIR, SYSTEM_PROMPTS_DIR, SAMPLES_DIR

_TMB_ROOT = TMB_ROOT  # backward compat alias

# Load .env: project root CWD wins over TMB/
load_dotenv(TMB_ROOT / ".env")           # legacy fallback
load_dotenv(TMB_ROOT / ".." / ".env", override=True)
_cwd_env = Path.cwd() / ".env"
if _cwd_env.exists() and _cwd_env.resolve() != (TMB_ROOT / ".env").resolve():
    load_dotenv(_cwd_env, override=True)


_DEFAULT_ROLE_NAMES = {
    "owner": "Project Owner",
    "planner": "Planner",
    "executor": "Executor",
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

    1. <project>/.tmb/config/<name>.yaml   (project-level user overrides)
    2. TMB/config/<name>.yaml              (legacy overrides inside framework)
    3. TMB/config/<name>.default.yaml      (tracked defaults)

    Uses _detect_project_root() instead of paths.user_cfg_dir() to avoid
    circular dependency (paths.py → config.py → paths.py).
    """
    project_override = _detect_project_root() / ".tmb" / "config" / f"{name}.yaml"
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
      1. <project>/.tmb/prompts/<name>.md  (auto-generated during setup)
      2. prompts/samples/<preset>/<name>.md  (if roles.preset is set)
      3. prompts/system/<name>.md  (TMB system default)

    Template variables like ``{role_planner}`` are replaced with display names
    from project.yaml → roles.
    """
    cfg = load_project_config()
    roles = cfg.get("roles") or {}
    preset = roles.get("preset")

    path = None

    # Priority 1: auto-generated prompts from setup
    user_path = _detect_project_root() / ".tmb" / "prompts" / f"{name}.md"
    if user_path.exists():
        path = user_path

    # Priority 2: static preset samples
    if path is None and preset:
        preset_path = SAMPLES_DIR / preset / f"{name}.md"
        if preset_path.exists():
            path = preset_path

    # Priority 3: TMB system default
    if path is None:
        path = SYSTEM_PROMPTS_DIR / f"{name}.md"

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
    tmb_resolved = TMB_ROOT.resolve()
    if cwd == tmb_resolved or str(cwd).startswith(str(tmb_resolved) + os.sep):
        return tmb_resolved.parent
    return cwd


def get_project_root() -> Path:
    """Resolve the target project root.

    Resolution order:
      1. ``root_dir`` in project.yaml (resolved relative to TMB_ROOT)
      2. Auto-detect from CWD via _detect_project_root()
    """
    cfg = load_project_config()
    raw = cfg.get("root_dir", "")
    if raw:
        return (TMB_ROOT / raw).resolve()
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


_PROVIDERS: dict[str, tuple[str, str, str | None]] = {
    "anthropic": ("langchain_anthropic",    "ChatAnthropic",           "ANTHROPIC_API_KEY"),
    "openai":    ("langchain_openai",       "ChatOpenAI",              "OPENAI_API_KEY"),
    "google":    ("langchain_google_genai",  "ChatGoogleGenerativeAI", "GOOGLE_API_KEY"),
    "groq":      ("langchain_groq",         "ChatGroq",               "GROQ_API_KEY"),
    "mistral":   ("langchain_mistralai",    "ChatMistralAI",          "MISTRAL_API_KEY"),
    "deepseek":  ("langchain_deepseek",     "ChatDeepSeek",           "DEEPSEEK_API_KEY"),
    "ollama":    ("langchain_ollama",       "ChatOllama",              None),
}


def _detect_gpu_layers() -> int:
    """Auto-detect GPU availability for Ollama.

    Returns:
        1 if GPU detected (Apple Silicon MPS or NVIDIA CUDA), 0 for CPU-only.
    """
    import platform
    import shutil
    import subprocess

    # macOS: Apple Silicon has MPS (Metal Performance Shaders)
    if platform.system() == "Darwin":
        if platform.machine() == "arm64":
            return 1  # Apple Silicon — MPS available
        return 0  # Intel Mac — no MPS

    # Linux/Windows: check for NVIDIA GPU via nvidia-smi
    if shutil.which("nvidia-smi"):
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return 1  # NVIDIA GPU available
        except (subprocess.TimeoutExpired, OSError):
            pass

    return 0  # No GPU detected


def get_llm(node_name: str):
    """Instantiate the LLM for a given node based on config/nodes.yaml.

    Supports any provider in _PROVIDERS. Packages are lazy-imported so only
    the one you configure needs to be installed.
    """
    import importlib

    cfg = load_nodes_config()[node_name]["model"]
    provider = cfg["provider"]
    model_name = cfg["name"]
    temperature = cfg.get("temperature", 0)
    base_url = cfg.get("base_url")
    timeout = cfg.get("timeout")  # seconds per LLM call; None means provider default

    if provider not in _PROVIDERS:
        supported = ", ".join(sorted(_PROVIDERS))
        raise ValueError(
            f"Unknown provider '{provider}'. Supported: {supported}"
        )

    package, class_name, env_var = _PROVIDERS[provider]
    pip_name = package.replace("_", "-")

    try:
        mod = importlib.import_module(package)
    except ImportError:
        # Detect if running as a uv tool or a local/project install
        from tmb.paths import TMB_ROOT
        try:
            project_root = get_project_root()
            is_tool = not TMB_ROOT.resolve().is_relative_to(project_root.resolve())
        except Exception:
            is_tool = False

        if is_tool:
            hint = f"uv tool install --with {pip_name} trustmybot"
        else:
            hint = f"uv add {pip_name}"

        raise ImportError(
            f"Provider '{provider}' requires the '{pip_name}' package.\n"
            f"Install it with:  {hint}"
        ) from None

    cls = getattr(mod, class_name)

    kwargs: dict = {"model": model_name, "temperature": temperature}
    if base_url:
        kwargs["base_url"] = base_url

    # Apply timeout — different providers use different kwargs
    if timeout is not None:
        if provider == "ollama":
            # ChatOllama passes timeout through client_kwargs to httpx
            kwargs["client_kwargs"] = {"timeout": timeout}
        else:
            # ChatAnthropic, ChatOpenAI, and most others accept `timeout`
            kwargs["timeout"] = timeout

    # Auto-detect or use configured GPU layers for Ollama
    if provider == "ollama":
        num_gpu = cfg.get("num_gpu")
        if num_gpu is None:
            num_gpu = _detect_gpu_layers()
        kwargs["num_gpu"] = num_gpu

    return cls(**kwargs)


class LLMConnectionError(Exception):
    """Raised when the LLM endpoint is unreachable or the model is unavailable."""
    pass


def safe_llm_invoke(llm, messages, *, label: str = "LLM"):
    """Invoke an LLM with friendly error handling for connection/timeout failures.

    Catches connection errors, timeouts, and model-not-found errors from any provider
    and raises LLMConnectionError with a human-friendly message.

    Raises:
        LLMConnectionError: with a user-friendly message describing what went wrong
    """
    try:
        return llm.invoke(messages)
    except Exception as e:
        error_str = str(e).lower()
        error_type = type(e).__name__

        # Connection refused / endpoint not running
        if any(term in error_str for term in ["connect", "connection refused", "no route to host"]):
            raise LLMConnectionError(
                f"Can't connect to the LLM. Is it running?\n"
                f"  If using Ollama: run 'ollama serve'\n"
                f"  If using LM Studio: start the local server\n"
                f"  Error: {error_type}: {str(e)[:200]}"
            ) from e

        # Timeout
        if any(term in error_str for term in ["timeout", "timed out", "deadline exceeded"]):
            raise LLMConnectionError(
                f"LLM call timed out. The model may be too slow for this prompt.\n"
                f"  Try: increase 'timeout' in .tmb/config/nodes.yaml\n"
                f"  Or: use a smaller/faster model\n"
                f"  Error: {error_type}: {str(e)[:200]}"
            ) from e

        # Model not found (Ollama-specific)
        if "not found" in error_str or "model" in error_str and "404" in error_str:
            raise LLMConnectionError(
                f"Model not found. Check the model name in .tmb/config/nodes.yaml\n"
                f"  If using Ollama: run 'ollama list' to see available models\n"
                f"  Error: {error_type}: {str(e)[:200]}"
            ) from e

        # Re-raise anything else (content errors, auth errors, etc.)
        raise


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
