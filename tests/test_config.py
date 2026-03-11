"""Tests for tmb.config — YAML loading, token extraction, role names."""

from __future__ import annotations

from unittest.mock import patch


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
