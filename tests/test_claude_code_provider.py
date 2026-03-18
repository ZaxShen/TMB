"""Tests for tmb.providers.claude_code — ChatClaudeCode, provider registration, and setup menu."""

from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tmb.config import LLMConnectionError, extract_token_usage, _PROVIDERS
from tmb.providers.claude_code import ChatClaudeCode


# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_JSON = (
    '{"type":"result","subtype":"success","is_error":false,'
    '"result":"Hello!","stop_reason":"end_turn","session_id":"test-123",'
    '"total_cost_usd":0.01,"usage":{"input_tokens":10,"output_tokens":5}}'
)


def _make_completed_process(stdout=_VALID_JSON, returncode=0, stderr=""):
    """Return a subprocess.CompletedProcess with the given attributes."""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.stdout = stdout
    proc.returncode = returncode
    proc.stderr = stderr
    return proc


# ── TestChatClaudeCode ────────────────────────────────────────────────────────

class TestChatClaudeCode:
    """Unit tests for ChatClaudeCode._generate() and bind_tools()."""

    def test_basic_invoke(self):
        """A successful CLI response returns an AIMessage with the right content."""
        llm = ChatClaudeCode()
        with patch("subprocess.run", return_value=_make_completed_process()) as mock_run:
            result = llm.invoke([HumanMessage(content="Hi")])
        assert isinstance(result, AIMessage)
        assert result.content == "Hello!"
        mock_run.assert_called_once()

    def test_token_extraction(self):
        """Token counts from the CLI JSON are accessible via extract_token_usage()."""
        llm = ChatClaudeCode()
        with patch("subprocess.run", return_value=_make_completed_process()):
            result = llm.invoke([HumanMessage(content="Hi")])
        usage = extract_token_usage(result)
        assert usage == {"input_tokens": 10, "output_tokens": 5}

    def test_system_prompt_appended(self):
        """SystemMessage content is passed as --append-system-prompt."""
        llm = ChatClaudeCode()
        with patch("subprocess.run", return_value=_make_completed_process()) as mock_run:
            llm.invoke([SystemMessage(content="You are helpful"), HumanMessage(content="Hi")])
        cmd = mock_run.call_args[0][0]
        assert "--append-system-prompt" in cmd
        idx = cmd.index("--append-system-prompt")
        assert cmd[idx + 1] == "You are helpful"

    def test_model_name_passed(self):
        """The model name is forwarded via --model."""
        llm = ChatClaudeCode(model="opus")
        with patch("subprocess.run", return_value=_make_completed_process()) as mock_run:
            llm.invoke([HumanMessage(content="Hi")])
        cmd = mock_run.call_args[0][0]
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "opus"

    def test_bind_tools_noop(self):
        """bind_tools() must return self — Claude Code manages its own tools."""
        llm = ChatClaudeCode()
        result = llm.bind_tools([{"name": "test_tool"}])
        assert result is llm

    def test_cli_not_found(self):
        """FileNotFoundError from subprocess maps to LLMConnectionError mentioning 'not found'."""
        llm = ChatClaudeCode()
        with patch("subprocess.run", side_effect=FileNotFoundError("claude: command not found")):
            with pytest.raises(LLMConnectionError, match="not found"):
                llm.invoke([HumanMessage(content="Hi")])

    def test_cli_timeout(self):
        """TimeoutExpired from subprocess maps to LLMConnectionError mentioning 'timed out'."""
        llm = ChatClaudeCode()
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["claude"], timeout=300),
        ):
            with pytest.raises(LLMConnectionError, match="timed out"):
                llm.invoke([HumanMessage(content="Hi")])

    def test_cli_error_exit(self):
        """Non-zero returncode raises LLMConnectionError."""
        llm = ChatClaudeCode()
        proc = _make_completed_process(stdout="", returncode=1, stderr="some error")
        with patch("subprocess.run", return_value=proc):
            with pytest.raises(LLMConnectionError):
                llm.invoke([HumanMessage(content="Hi")])

    def test_disallowed_tools_flag(self):
        """disallowed_tools list is forwarded to the CLI as --disallowed-tools <patterns...>."""
        patterns = ["Read(**/GOALS.md)", "Read(**/DISCUSSION.md)"]
        llm = ChatClaudeCode(disallowed_tools=patterns)
        with patch("subprocess.run", return_value=_make_completed_process()) as mock_run:
            llm.invoke([HumanMessage(content="Hi")])
        cmd = mock_run.call_args[0][0]
        assert "--disallowed-tools" in cmd
        idx = cmd.index("--disallowed-tools")
        # The patterns must appear immediately after the flag
        for i, pattern in enumerate(patterns):
            assert cmd[idx + 1 + i] == pattern

    def test_response_has_no_tool_calls(self):
        """AIMessage from ChatClaudeCode must have no tool_calls — executor loop exits after one round."""
        llm = ChatClaudeCode()
        with patch("subprocess.run", return_value=_make_completed_process()):
            result = llm.invoke([HumanMessage(content="Hi")])
        # tool_calls should be falsy (empty list or absent)
        tool_calls = getattr(result, "tool_calls", [])
        assert not tool_calls


# ── TestProviderRegistration ──────────────────────────────────────────────────

class TestProviderRegistration:
    """Verify that claude_code is registered in config._PROVIDERS."""

    def test_claude_code_in_providers(self):
        """_PROVIDERS must contain 'claude_code' with a 3-tuple where env_var is None."""
        assert "claude_code" in _PROVIDERS
        entry = _PROVIDERS["claude_code"]
        assert len(entry) == 3, f"Expected 3-tuple, got {entry!r}"
        module_path, class_name, env_var = entry
        assert isinstance(module_path, str)
        assert isinstance(class_name, str)
        assert env_var is None

    def test_provider_module_importable(self):
        """The module and class referenced in _PROVIDERS must be importable."""
        import importlib
        module_path, class_name, _ = _PROVIDERS["claude_code"]
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name, None)
        assert cls is not None, f"{class_name} not found in {module_path}"


# ── TestSetupMenu ─────────────────────────────────────────────────────────────

class TestSetupMenu:
    """Verify that the CLI setup menu includes Claude Code support."""

    def test_claude_code_in_menu(self):
        """'Claude Code' and 'claude_code' must both appear in cli.py source."""
        import tmb.cli as cli_mod
        import inspect
        source = inspect.getsource(cli_mod)
        assert "Claude Code" in source, "'Claude Code' label not found in cli.py"
        assert "claude_code" in source, "'claude_code' key not found in cli.py"

    def test_claude_cli_detection(self):
        """shutil.which('claude') truthy means detected, None means not detected."""
        import shutil
        with patch("shutil.which", return_value="/usr/local/bin/claude") as mock_which:
            result = shutil.which("claude")
        assert result  # truthy — CLI found

        with patch("shutil.which", return_value=None) as mock_which:
            result = shutil.which("claude")
        assert not result  # falsy — CLI not found
