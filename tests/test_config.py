"""Tests for tmb.config — YAML loading, token extraction, role names, GPU detection."""

from __future__ import annotations

import sys
from unittest.mock import patch, MagicMock
import pytest


def test_load_yaml(tmp_path):
    from tmb.config import load_yaml

    yaml_file = tmp_path / "test.yaml"
    yaml_file.write_text("name: hello\nitems:\n  - a\n  - b\n")

    result = load_yaml(yaml_file)
    assert result["name"] == "hello"
    assert result["items"] == ["a", "b"]


def test_load_yaml_missing_file(tmp_path):
    from tmb.config import load_yaml
    import pytest

    with pytest.raises(FileNotFoundError):
        load_yaml(tmp_path / "nonexistent.yaml")


def test_extract_token_usage_anthropic():
    from tmb.config import extract_token_usage

    class FakeResponse:
        response_metadata = {"usage": {"input_tokens": 1234, "output_tokens": 567}}

    result = extract_token_usage(FakeResponse())
    assert result == {"input_tokens": 1234, "output_tokens": 567}


def test_extract_token_usage_openai():
    from tmb.config import extract_token_usage

    class FakeResponse:
        response_metadata = {"token_usage": {"prompt_tokens": 100, "completion_tokens": 50}}

    result = extract_token_usage(FakeResponse())
    assert result == {"input_tokens": 100, "output_tokens": 50}


def test_extract_token_usage_empty():
    from tmb.config import extract_token_usage

    class FakeResponse:
        response_metadata = {}

    result = extract_token_usage(FakeResponse())
    assert result == {"input_tokens": 0, "output_tokens": 0}


def test_get_role_name_defaults():
    from tmb.config import get_role_name

    with patch("tmb.config.load_project_config", return_value={}):
        assert get_role_name("planner") == "Planner"
        assert get_role_name("executor") == "Executor"
        assert get_role_name("owner") == "Project Owner"


def test_get_role_name_custom():
    from tmb.config import get_role_name

    cfg = {"roles": {"planner": "Architect", "executor": "SWE"}}
    with patch("tmb.config.load_project_config", return_value=cfg):
        assert get_role_name("planner") == "Architect"
        assert get_role_name("executor") == "SWE"
        assert get_role_name("owner") == "Project Owner"


class TestGetLlmOllama:
    """Tests for get_llm() with the Ollama provider."""

    @staticmethod
    def _make_nodes_config(provider="ollama", model="llama3.2",
                            temperature=0.3, base_url=None, timeout=None):
        """Build a minimal nodes config for testing."""
        model_cfg = {"provider": provider, "name": model, "temperature": temperature}
        if base_url:
            model_cfg["base_url"] = base_url
        if timeout is not None:
            model_cfg["timeout"] = timeout
        return {"planner": {"model": model_cfg, "tools": []}}

    def test_ollama_instantiation(self):
        """get_llm with ollama should import langchain_ollama and call ChatOllama."""
        mock_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.ChatOllama = mock_cls

        config = self._make_nodes_config()

        with (
            patch("tmb.config.load_nodes_config", return_value=config),
            patch("importlib.import_module", return_value=mock_module) as mock_import,
        ):
            from tmb.config import get_llm
            result = get_llm("planner")

        mock_import.assert_called_with("langchain_ollama")
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == "llama3.2"
        assert call_kwargs["temperature"] == 0.3
        assert "num_gpu" in call_kwargs  # auto-detected
        assert isinstance(call_kwargs["num_gpu"], int)
        assert result == mock_cls.return_value

    def test_ollama_with_base_url(self):
        """base_url should be passed through to ChatOllama."""
        mock_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.ChatOllama = mock_cls

        config = self._make_nodes_config(base_url="http://localhost:11434")

        with (
            patch("tmb.config.load_nodes_config", return_value=config),
            patch("importlib.import_module", return_value=mock_module),
        ):
            from tmb.config import get_llm
            get_llm("planner")

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["base_url"] == "http://localhost:11434"
        assert "num_gpu" in call_kwargs

    def test_ollama_no_api_key_required(self):
        """Ollama has env_var=None — should work without any API key set."""
        mock_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.ChatOllama = mock_cls

        config = self._make_nodes_config()

        # Ensure no Ollama-related env vars are set
        with (
            patch("tmb.config.load_nodes_config", return_value=config),
            patch("importlib.import_module", return_value=mock_module),
            patch.dict("os.environ", {}, clear=False),
        ):
            from tmb.config import get_llm
            # Should not raise — no API key needed
            result = get_llm("planner")

        assert result is not None

    def test_ollama_missing_package(self):
        """Missing langchain-ollama should raise ImportError with install hint."""
        config = self._make_nodes_config()

        with (
            patch("tmb.config.load_nodes_config", return_value=config),
            patch("importlib.import_module", side_effect=ImportError("No module")),
        ):
            from tmb.config import get_llm
            with pytest.raises(ImportError, match="langchain-ollama"):
                get_llm("planner")

    def test_unknown_provider_raises(self):
        """Unknown provider should raise ValueError with supported list."""
        config = self._make_nodes_config(provider="nonexistent")

        with patch("tmb.config.load_nodes_config", return_value=config):
            from tmb.config import get_llm
            with pytest.raises(ValueError, match="nonexistent"):
                get_llm("planner")

    def test_ollama_timeout_uses_client_kwargs(self):
        """Ollama timeout must be passed as client_kwargs={'timeout': N}, not as timeout=N."""
        mock_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.ChatOllama = mock_cls

        config = self._make_nodes_config(timeout=300)

        with (
            patch("tmb.config.load_nodes_config", return_value=config),
            patch("importlib.import_module", return_value=mock_module),
        ):
            from tmb.config import get_llm
            get_llm("planner")

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["client_kwargs"] == {"timeout": 300}
        assert "num_gpu" in call_kwargs

    def test_non_ollama_timeout_uses_timeout_kwarg(self):
        """Non-Ollama providers (e.g. anthropic) should receive timeout= directly."""
        mock_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.ChatAnthropic = mock_cls

        config = self._make_nodes_config(provider="anthropic", model="claude-3-5-haiku-20241022", timeout=120)

        with (
            patch("tmb.config.load_nodes_config", return_value=config),
            patch("importlib.import_module", return_value=mock_module),
        ):
            from tmb.config import get_llm
            get_llm("planner")

        mock_cls.assert_called_once_with(
            model="claude-3-5-haiku-20241022", temperature=0.3, timeout=120
        )

    def test_no_timeout_config_passes_no_timeout_kwarg(self):
        """When timeout is not in config, no timeout kwarg should be passed."""
        mock_cls = MagicMock()
        mock_module = MagicMock()
        mock_module.ChatOllama = mock_cls

        config = self._make_nodes_config()  # no timeout

        with (
            patch("tmb.config.load_nodes_config", return_value=config),
            patch("importlib.import_module", return_value=mock_module),
        ):
            from tmb.config import get_llm
            get_llm("planner")

        call_kwargs = mock_cls.call_args[1]
        assert "timeout" not in call_kwargs
        assert "client_kwargs" not in call_kwargs
        assert "num_gpu" in call_kwargs  # always present for Ollama


# ── GPU detection tests ──────────────────────────────────────────────

def test_detect_gpu_layers_returns_int():
    """_detect_gpu_layers should return 0 or 1."""
    from tmb.config import _detect_gpu_layers
    result = _detect_gpu_layers()
    assert isinstance(result, int)
    assert result in (0, 1)


def test_detect_gpu_layers_apple_silicon():
    """Apple Silicon (arm64 + Darwin) should return 1."""
    from tmb.config import _detect_gpu_layers
    with (
        patch("platform.system", return_value="Darwin"),
        patch("platform.machine", return_value="arm64"),
    ):
        assert _detect_gpu_layers() == 1


def test_detect_gpu_layers_intel_mac():
    """Intel Mac (x86_64 + Darwin) should return 0."""
    from tmb.config import _detect_gpu_layers
    with (
        patch("platform.system", return_value="Darwin"),
        patch("platform.machine", return_value="x86_64"),
    ):
        assert _detect_gpu_layers() == 0


def test_detect_gpu_layers_nvidia():
    """Linux with nvidia-smi should return 1."""
    from tmb.config import _detect_gpu_layers
    import subprocess
    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stdout = "NVIDIA GeForce RTX 3090\n"

    with (
        patch("platform.system", return_value="Linux"),
        patch("shutil.which", return_value="/usr/bin/nvidia-smi"),
        patch("subprocess.run", return_value=fake_result),
    ):
        assert _detect_gpu_layers() == 1


def test_detect_gpu_layers_no_gpu_linux():
    """Linux without nvidia-smi should return 0."""
    from tmb.config import _detect_gpu_layers

    with (
        patch("platform.system", return_value="Linux"),
        patch("shutil.which", return_value=None),
    ):
        assert _detect_gpu_layers() == 0


def test_get_llm_ollama_passes_num_gpu():
    """get_llm should pass num_gpu to ChatOllama (auto-detected)."""
    import tmb.config as config_mod

    mock_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.ChatOllama = mock_cls

    config = {"planner": {"model": {
        "provider": "ollama", "name": "llama3.1:8b", "temperature": 0.3,
    }}}

    with (
        patch.object(config_mod, "load_nodes_config", return_value=config),
        patch("importlib.import_module", return_value=mock_module),
        patch.object(config_mod, "_detect_gpu_layers", return_value=1),
    ):
        config_mod.get_llm("planner")

    call_kwargs = mock_cls.call_args[1]
    assert call_kwargs["num_gpu"] == 1


def test_get_llm_ollama_config_num_gpu_override():
    """Explicit num_gpu in config should override auto-detection."""
    import tmb.config as config_mod

    mock_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.ChatOllama = mock_cls

    config = {"planner": {"model": {
        "provider": "ollama", "name": "llama3.1:8b", "temperature": 0.3,
        "num_gpu": 0,  # explicit CPU override
    }}}

    with (
        patch.object(config_mod, "load_nodes_config", return_value=config),
        patch("importlib.import_module", return_value=mock_module),
        patch.object(config_mod, "_detect_gpu_layers", return_value=1),  # detection says GPU, but config says 0
    ):
        config_mod.get_llm("planner")

    call_kwargs = mock_cls.call_args[1]
    assert call_kwargs["num_gpu"] == 0  # config overrides detection


def test_get_llm_non_ollama_no_num_gpu():
    """Non-Ollama providers should NOT get num_gpu."""
    mock_cls = MagicMock()
    mock_module = MagicMock()
    mock_module.ChatAnthropic = mock_cls

    config = {"planner": {"model": {
        "provider": "anthropic", "name": "claude-3-5-haiku-20241022", "temperature": 0.3,
    }}}

    with (
        patch("tmb.config.load_nodes_config", return_value=config),
        patch("importlib.import_module", return_value=mock_module),
    ):
        from tmb.config import get_llm
        get_llm("planner")

    call_kwargs = mock_cls.call_args[1]
    assert "num_gpu" not in call_kwargs


# ── Pydantic V1 warning suppression ─────────────────────────────────

def test_pydantic_v1_warning_suppressed():
    """The Pydantic V1 compat warning filter should be established by cli.py."""
    import warnings
    import importlib
    import tmb.cli
    # Reload to re-execute the module-level filterwarnings call
    # (pytest resets warning filters between tests)
    importlib.reload(tmb.cli)
    filters = [f for f in warnings.filters if "Pydantic V1" in str(f)]
    assert len(filters) >= 1, "Pydantic V1 warning filter not found after importing tmb.cli"
