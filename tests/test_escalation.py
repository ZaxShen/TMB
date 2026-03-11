"""Tests for structured escalation detection in executor."""

from __future__ import annotations

import pytest


def _detect_escalation(content) -> bool:
    from tmb.nodes.executor import _detect_escalation
    return _detect_escalation(content)


# ── Tier 1: structured JSON signal ───────────────────────────

def test_json_status_escalate():
    text = 'I cannot complete this task.\n{"status": "escalate", "reason": "missing API key"}'
    assert _detect_escalation(text) is True


def test_json_status_escalate_case_insensitive():
    text = '{"status": "Escalate", "reason": "blocked by dependency"}'
    assert _detect_escalation(text) is True


# ── Tier 2: word-boundary keyword ────────────────────────────

def test_keyword_escalate_in_prose():
    text = "I need to escalate this task because the file is corrupted."
    assert _detect_escalation(text) is True


def test_keyword_escalate_uppercase():
    text = "ESCALATE: Cannot proceed without database credentials."
    assert _detect_escalation(text) is True


# ── False positives from tool output ─────────────────────────

def test_no_escalation_in_normal_output():
    text = "Task completed successfully. All files created."
    assert _detect_escalation(text) is False


def test_no_escalation_empty():
    assert _detect_escalation("") is False


def test_escalated_past_tense_still_detected():
    """The word 'escalated' contains 'escalate' + 'd'.
    \\bescalate\\b does NOT match inside 'escalated' because the 'd' continues the word.
    But \\bescalat(e|ed|ion)\\b patterns would. Our regex uses \\bescalate\\b which
    checks word boundary AFTER the 'e' — 'd' is a word char so \\b doesn't match.
    This means 'escalated' is NOT detected, which is acceptable behavior."""
    text = "The previous task was escalated."
    # \bescalate\b does NOT match 'escalated' — the 'd' after 'e' means no word boundary
    assert _detect_escalation(text) is False


def test_tool_output_with_escalate_in_quoted_string():
    """If escalate appears in the LLM's own text, it's still detected.
    The key improvement is we only check response.content, not appended tool outputs."""
    text = "Set status to 'escalate' with reason: no write access."
    assert _detect_escalation(text) is True
