"""Tests for XML-based escalation detection in executor."""

from __future__ import annotations

import pytest


def _detect_escalation(content) -> bool:
    from tmb.nodes.executor import _detect_escalation
    return _detect_escalation(content)


# ── Tier 1: XML status tag ───────────────────────────────────

def test_xml_status_escalate():
    text = "I cannot complete this task.\n<status>escalate</status>\n<escalation_reason>missing API key</escalation_reason>"
    assert _detect_escalation(text) is True


def test_xml_status_escalate_case_insensitive():
    text = "<status>Escalate</status>"
    assert _detect_escalation(text) is True


def test_xml_status_completed():
    text = "<status>completed</status>\n<summary>Done</summary>"
    assert _detect_escalation(text) is False


def test_xml_status_failed():
    text = "<status>failed</status>\n<summary>Could not finish</summary>"
    assert _detect_escalation(text) is False


# ── Tier 2: word-boundary keyword ────────────────────────────

def test_keyword_escalate_in_prose():
    text = "I need to escalate this task because the file is corrupted."
    assert _detect_escalation(text) is True


def test_keyword_escalate_uppercase():
    text = "ESCALATE: Cannot proceed without database credentials."
    assert _detect_escalation(text) is True


# ── False positives ──────────────────────────────────────────

def test_no_escalation_in_normal_output():
    text = "Task completed successfully. All files created."
    assert _detect_escalation(text) is False


def test_no_escalation_empty():
    assert _detect_escalation("") is False


def test_escalated_past_tense_not_detected():
    text = "The previous task was escalated."
    assert _detect_escalation(text) is False


def test_tool_output_with_escalate_in_quoted_string():
    text = "Set status to 'escalate' with reason: no write access."
    assert _detect_escalation(text) is True
