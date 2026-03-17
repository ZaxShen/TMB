"""Tests for tmb/monitor.py — dashboard renderer and formatting helpers."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from tmb.monitor import (
    _format_elapsed,
    _format_tokens,
    _task_icon,
    is_terminal,
    render_dashboard,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _iso_ago(seconds: float) -> str:
    """Return an ISO-8601 UTC timestamp that is ``seconds`` in the past."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return ts.isoformat()


def _create_task(store, issue_id: int, branch_id: str, description: str = "Task description"):
    """Create a single task using the blueprint API."""
    store.create_tasks(issue_id, [
        {
            "branch_id": branch_id,
            "description": description,
            "success_criteria": "check it works",
            "tools_required": [],
            "skills_required": [],
        }
    ])


# ---------------------------------------------------------------------------
# TestFormatElapsed
# ---------------------------------------------------------------------------

class TestFormatElapsed:
    def test_format_elapsed_seconds(self):
        ts = _iso_ago(30)
        result = _format_elapsed(ts)
        assert "s" in result
        # Should contain a digit
        assert any(ch.isdigit() for ch in result)

    def test_format_elapsed_minutes(self):
        ts = _iso_ago(150)
        result = _format_elapsed(ts)
        assert "m" in result

    def test_format_elapsed_hours(self):
        ts = _iso_ago(4000)
        result = _format_elapsed(ts)
        assert "h" in result

    def test_format_elapsed_none(self):
        result = _format_elapsed(None)
        assert result == "\u2014"  # em-dash

    def test_format_elapsed_malformed(self):
        result = _format_elapsed("not-a-date")
        assert result == "\u2014"  # em-dash


# ---------------------------------------------------------------------------
# TestTaskIcon
# ---------------------------------------------------------------------------

class TestTaskIcon:
    def test_completed(self):
        assert _task_icon("completed") == "\u2705"  # ✅

    def test_in_progress(self):
        assert _task_icon("in_progress") == "\U0001f527"  # 🔧

    def test_pending(self):
        assert _task_icon("pending") == "\u23f3"  # ⏳

    def test_failed(self):
        assert _task_icon("failed") == "\u274c"  # ❌

    def test_escalated(self):
        assert _task_icon("escalated") == "\u26a0\ufe0f"  # ⚠️

    def test_unknown(self):
        assert _task_icon("whatever") == "\u2753"  # ❓


# ---------------------------------------------------------------------------
# TestFormatTokens
# ---------------------------------------------------------------------------

class TestFormatTokens:
    def test_small(self):
        assert _format_tokens(892) == "892"

    def test_thousands(self):
        assert _format_tokens(3200) == "3.2K"

    def test_millions(self):
        assert _format_tokens(1_500_000) == "1.5M"

    def test_zero(self):
        assert _format_tokens(0) == "0"

    def test_exactly_1000(self):
        assert _format_tokens(1000) == "1.0K"


# ---------------------------------------------------------------------------
# TestIsTerminal
# ---------------------------------------------------------------------------

class TestIsTerminal:
    def test_is_terminal_true(self):
        with patch.object(sys.stdout, "isatty", return_value=True):
            assert is_terminal() is True

    def test_is_terminal_false(self):
        with patch.object(sys.stdout, "isatty", return_value=False):
            assert is_terminal() is False


# ---------------------------------------------------------------------------
# TestRenderDashboard
# ---------------------------------------------------------------------------

class TestRenderDashboard:
    def test_basic_render(self, store):
        issue_id = store.create_issue("Test objective", "goals")
        # Create both tasks in a single call (create_tasks replaces all tasks)
        store.create_tasks(issue_id, [
            {
                "branch_id": "1",
                "description": "First task",
                "success_criteria": "check it works",
                "tools_required": [],
                "skills_required": [],
            },
            {
                "branch_id": "2",
                "description": "Second task",
                "success_criteria": "check it works",
                "tools_required": [],
                "skills_required": [],
            },
        ])
        # Mark the first task completed
        store.update_task_status(issue_id, "1", "completed")

        result = render_dashboard(store, issue_id)
        assert f"Issue #{issue_id}" in result
        assert "Test objective" in result
        assert "\u2705" in result   # ✅ completed
        assert "\u23f3" in result   # ⏳ pending
        assert "\u2554" in result   # ╔ top-left corner
        assert "\u2551" in result   # ║ side border
        assert "\u255a" in result   # ╚ bottom-left corner

    def test_render_no_tasks(self, store):
        issue_id = store.create_issue("Solo issue", "goals")
        result = render_dashboard(store, issue_id)
        assert f"Issue #{issue_id}" in result
        # Should not raise and should still produce box output
        assert "\u2554" in result

    def test_render_all_completed(self, store):
        issue_id = store.create_issue("All done objective", "goals")
        blueprint = [
            {
                "branch_id": str(i),
                "description": f"Task {i}",
                "success_criteria": "done",
                "tools_required": [],
                "skills_required": [],
            }
            for i in range(1, 4)
        ]
        store.create_tasks(issue_id, blueprint)
        for i in range(1, 4):
            store.update_task_status(issue_id, str(i), "completed")

        result = render_dashboard(store, issue_id)
        # Either "3/3" summary or three checkmarks
        assert "3/3" in result or result.count("\u2705") == 3

    def test_render_with_tokens(self, store):
        issue_id = store.create_issue("Token objective", "goals")
        store.log_tokens(issue_id, "executor", 1200, 800)
        result = render_dashboard(store, issue_id)
        assert "Tokens:" in result

    def test_render_issue_not_found(self, store):
        result = render_dashboard(store, 9999)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "not found" in result.lower() or "9999" in result

    def test_render_custom_width(self, store):
        issue_id = store.create_issue("Width test objective", "goals")
        result = render_dashboard(store, issue_id, width=120)
        # The first line (top border) should be exactly 120 chars wide
        first_line = result.split("\n")[0]
        assert len(first_line) == 120
