"""Tests for chat mode signal parsing, command dispatch, routing, and discussion prompt."""

import re
import pytest


# ── Signal Parser Tests ──────────────────────────────────

class TestExtractChatSignal:
    """Tests for _extract_chat_signal()."""

    def test_quick_task_signal(self):
        from tmb.cli import _extract_chat_signal
        sig, val, txt = _extract_chat_signal(
            "I'll fix that for you. <quick_task>Fix typo in README.md</quick_task>"
        )
        assert sig == "quick_task"
        assert val == "Fix typo in README.md"
        assert "<quick_task>" not in txt
        assert "I'll fix that for you." in txt

    def test_plan_mode_signal(self):
        from tmb.cli import _extract_chat_signal
        sig, val, txt = _extract_chat_signal(
            "This needs planning. <plan_mode>Redesign auth system with JWT</plan_mode>"
        )
        assert sig == "plan"
        assert val == "Redesign auth system with JWT"
        assert "<plan_mode>" not in txt

    def test_run_command_signal(self):
        from tmb.cli import _extract_chat_signal
        sig, val, txt = _extract_chat_signal(
            "I'll check that. <run_command>log 5</run_command>"
        )
        assert sig == "command"
        assert val == "log 5"
        assert "<run_command>" not in txt

    def test_no_signal(self):
        from tmb.cli import _extract_chat_signal
        sig, val, txt = _extract_chat_signal("Just a normal answer about the code.")
        assert sig is None
        assert val is None
        assert txt == "Just a normal answer about the code."

    def test_strips_tags_completely(self):
        from tmb.cli import _extract_chat_signal
        _, _, txt = _extract_chat_signal(
            "Hello world <quick_task>do stuff</quick_task>"
        )
        assert "quick_task" not in txt
        assert "do stuff" not in txt
        assert "Hello world" in txt

    def test_multiline_tag_content(self):
        from tmb.cli import _extract_chat_signal
        sig, val, txt = _extract_chat_signal(
            "Here's the plan. <plan_mode>Step 1: Do X\nStep 2: Do Y\nStep 3: Do Z</plan_mode>"
        )
        assert sig == "plan"
        assert "Step 1" in val
        assert "Step 3" in val

    def test_command_with_no_args(self):
        from tmb.cli import _extract_chat_signal
        sig, val, txt = _extract_chat_signal(
            "Scanning now. <run_command>scan</run_command>"
        )
        assert sig == "command"
        assert val == "scan"

    def test_command_priority_over_quick_task(self):
        """If both command and quick_task tags exist (shouldn't happen), command wins."""
        from tmb.cli import _extract_chat_signal
        sig, val, _ = _extract_chat_signal(
            "<run_command>scan</run_command> <quick_task>fix</quick_task>"
        )
        assert sig == "command"

    def test_empty_tag_content(self):
        from tmb.cli import _extract_chat_signal
        sig, val, txt = _extract_chat_signal(
            "Hmm. <quick_task></quick_task>"
        )
        assert sig == "quick_task"
        assert val == ""

    def test_tag_at_start(self):
        from tmb.cli import _extract_chat_signal
        sig, val, txt = _extract_chat_signal(
            "<run_command>version</run_command>"
        )
        assert sig == "command"
        assert val == "version"


# ── Command Dispatch Tests ───────────────────────────────

class TestDispatchChatCommand:
    """Tests for _dispatch_chat_command()."""

    def test_dispatch_scan(self, monkeypatch):
        from tmb.cli import _dispatch_chat_command
        from tmb.store import Store
        import tempfile, os
        db = tempfile.mktemp(suffix=".db")
        store = Store(db)

        called = []
        monkeypatch.setattr("tmb.cli.scan", lambda: called.append("scan"))
        result = _dispatch_chat_command("scan", store)
        assert result is True  # Continue chat
        assert called == ["scan"]
        os.unlink(db)

    def test_dispatch_log(self, monkeypatch):
        from tmb.cli import _dispatch_chat_command
        from tmb.store import Store
        import tempfile, os
        db = tempfile.mktemp(suffix=".db")
        store = Store(db)

        called = []
        monkeypatch.setattr("tmb.cli.log_history", lambda x: called.append(("log", x)))
        result = _dispatch_chat_command("log", store)
        assert result is True
        assert called == [("log", None)]
        os.unlink(db)

    def test_dispatch_log_with_id(self, monkeypatch):
        from tmb.cli import _dispatch_chat_command
        from tmb.store import Store
        import tempfile, os
        db = tempfile.mktemp(suffix=".db")
        store = Store(db)

        called = []
        monkeypatch.setattr("tmb.cli.log_history", lambda x: called.append(("log", x)))
        result = _dispatch_chat_command("log 5", store)
        assert result is True
        assert called == [("log", 5)]
        os.unlink(db)

    def test_dispatch_version(self, monkeypatch):
        from tmb.cli import _dispatch_chat_command
        from tmb.store import Store
        import tempfile, os
        db = tempfile.mktemp(suffix=".db")
        store = Store(db)

        result = _dispatch_chat_command("version", store)
        assert result is True
        os.unlink(db)

    def test_dispatch_unknown_command(self, monkeypatch, capsys):
        from tmb.cli import _dispatch_chat_command
        from tmb.store import Store
        import tempfile, os
        db = tempfile.mktemp(suffix=".db")
        store = Store(db)

        result = _dispatch_chat_command("nonexistent", store)
        assert result is True  # Should continue chat, not crash
        captured = capsys.readouterr()
        assert "Unknown command" in captured.out
        os.unlink(db)

    def test_dispatch_setup_needs_confirm(self, monkeypatch):
        from tmb.cli import _dispatch_chat_command
        from tmb.store import Store
        import tempfile, os
        db = tempfile.mktemp(suffix=".db")
        store = Store(db)

        setup_called = []
        monkeypatch.setattr("tmb.cli.setup", lambda: setup_called.append(True))
        monkeypatch.setattr("builtins.input", lambda _: "n")
        result = _dispatch_chat_command("setup", store)
        assert result is True
        assert setup_called == []  # Not called when user says no
        os.unlink(db)

    def test_dispatch_report_needs_arg(self, capsys):
        from tmb.cli import _dispatch_chat_command
        from tmb.store import Store
        import tempfile, os
        db = tempfile.mktemp(suffix=".db")
        store = Store(db)

        result = _dispatch_chat_command("report", store)
        assert result is True
        captured = capsys.readouterr()
        assert "Usage" in captured.out or "report" in captured.out.lower()
        os.unlink(db)


# ── CLI Routing Tests ────────────────────────────────────

class TestCLIRouting:
    """Tests for main() dispatch routing."""

    def test_known_commands_includes_plan(self):
        from tmb.cli import _KNOWN_COMMANDS
        assert "plan" in _KNOWN_COMMANDS

    def test_main_no_args_calls_chat(self, monkeypatch):
        import sys
        from tmb import cli
        monkeypatch.setattr(sys, "argv", ["bro"])
        called = []
        monkeypatch.setattr(cli, "chat", lambda **kw: called.append(("chat", kw)))
        # Patch chat to accept no args too
        monkeypatch.setattr(cli, "chat", lambda initial_message=None: called.append(("chat", initial_message)))
        cli.main()
        assert len(called) == 1
        assert called[0] == ("chat", None)

    def test_main_plan_calls_plan(self, monkeypatch):
        import sys
        from tmb import cli
        monkeypatch.setattr(sys, "argv", ["bro", "plan"])
        called = []
        monkeypatch.setattr(cli, "plan", lambda: called.append("plan"))
        cli.main()
        assert called == ["plan"]

    def test_main_text_calls_chat_with_message(self, monkeypatch):
        import sys
        from tmb import cli
        monkeypatch.setattr(sys, "argv", ["bro", "fix", "this", "bug"])
        called = []
        monkeypatch.setattr(cli, "chat", lambda initial_message=None: called.append(("chat", initial_message)))
        cli.main()
        assert len(called) == 1
        assert called[0] == ("chat", "fix this bug")


# ── Discussion Prompt Tests ──────────────────────────────

class TestDiscussionPrompt:
    """Tests for discussion system prompt content."""

    def test_discussion_system_has_multichoice(self):
        from tmb.nodes.discussion import _DISCUSSION_SYSTEM
        assert "(a)" in _DISCUSSION_SYSTEM
        assert "(b)" in _DISCUSSION_SYSTEM
        assert "(other)" in _DISCUSSION_SYSTEM

    def test_discussion_system_has_template_vars(self):
        from tmb.nodes.discussion import _DISCUSSION_SYSTEM
        assert "{role_planner}" in _DISCUSSION_SYSTEM
        assert "{role_owner}" in _DISCUSSION_SYSTEM

    def test_discussion_system_has_ready_signal(self):
        from tmb.nodes.discussion import _DISCUSSION_SYSTEM, _READY_SIGNAL
        assert _READY_SIGNAL in _DISCUSSION_SYSTEM
