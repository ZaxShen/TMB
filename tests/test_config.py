"""Tests for tmb.config — YAML loading, token extraction, role names."""

from __future__ import annotations

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
                            temperature=0.3, base_url=None):
        """Build a minimal nodes config for testing."""
        model_cfg = {"provider": provider, "name": model, "temperature": temperature}
        if base_url:
            model_cfg["base_url"] = base_url
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
        mock_cls.assert_called_once_with(model="llama3.2", temperature=0.3)
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

        mock_cls.assert_called_once_with(
            model="llama3.2", temperature=0.3, base_url="http://localhost:11434"
        )

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
