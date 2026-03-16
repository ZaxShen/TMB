"""Tests for _extract_verdict_xml() — XML tags, keyword fallback, and edge cases."""

from __future__ import annotations

import pytest


def _extract_verdict(text: str) -> bool:
    from tmb.nodes.planner import _extract_verdict_xml
    return _extract_verdict_xml(text)


# ── Tier 1: XML tag ──────────────────────────────────────────

def test_xml_tag_pass():
    text = "<verdict>PASS</verdict>"
    assert _extract_verdict(text) is True


def test_xml_tag_fail():
    text = "<verdict>FAIL</verdict>"
    assert _extract_verdict(text) is False


def test_xml_tag_case_insensitive():
    text = "<verdict>pass</verdict>"
    assert _extract_verdict(text) is True


def test_xml_tag_with_evidence():
    text = "<verdict>PASS</verdict>\n<evidence>all tests pass</evidence>"
    assert _extract_verdict(text) is True


def test_xml_tag_with_surrounding_prose():
    text = "After thorough review:\n\n<verdict>FAIL</verdict>\n\nThe output was incorrect."
    assert _extract_verdict(text) is False


# ── XML tag beats contradictory keywords ──────────────────────

def test_pass_keyword_before_fail_verdict():
    """PASS keyword in prose but <verdict>FAIL</verdict> is authoritative."""
    text = "While PASS rate was high, critical tests broke.\n<verdict>FAIL</verdict>"
    assert _extract_verdict(text) is False


def test_fail_keyword_before_pass_verdict():
    """FAIL keyword in prose but <verdict>PASS</verdict> is authoritative."""
    text = "This is not a FAIL. Everything works.\n<verdict>PASS</verdict>"
    assert _extract_verdict(text) is True


def test_tool_output_json_before_verdict():
    """Tool output with JSON containing 'verdict' key before actual XML verdict."""
    text = (
        'Tool output: {"status": "ok", "verdict": "PASS", "count": 5}\n\n'
        "But the actual task failed.\n<verdict>FAIL</verdict>"
    )
    assert _extract_verdict(text) is False


# ── Tier 2: keyword fallback ─────────────────────────────────

def test_keyword_pass_standalone():
    text = "The task PASS — everything looks good."
    assert _extract_verdict(text) is True


def test_keyword_fail_standalone():
    text = "The validation result is FAIL due to missing output."
    assert _extract_verdict(text) is False


def test_password_should_not_match_pass():
    text = "Set the password to something secure."
    assert _extract_verdict(text) is False


def test_passthrough_should_not_match_pass():
    text = "Use passthrough mode for the proxy."
    assert _extract_verdict(text) is False


def test_bypass_should_not_match_fail():
    text = "You can bypass the cache for testing."
    assert _extract_verdict(text) is False


def test_both_keywords_last_wins():
    """When both keywords present without XML tags, LAST one wins."""
    assert _extract_verdict("PASS initially but ended in FAIL") is False
    assert _extract_verdict("First FAIL then corrected to PASS") is True


# ── Tier 3: fail-closed default ──────────────────────────────

def test_empty_string_defaults_to_fail():
    assert _extract_verdict("") is False


def test_no_verdict_keyword_defaults_to_fail():
    text = "The task completed with some warnings."
    assert _extract_verdict(text) is False


def test_garbage_defaults_to_fail():
    text = "asdf 1234 !@#$"
    assert _extract_verdict(text) is False
