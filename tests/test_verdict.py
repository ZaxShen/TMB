"""Tests for _extract_verdict() — structured, keyword, and edge cases."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _silence_logging():
    """Suppress logging warnings during tests."""
    import logging
    logging.getLogger("tmb.planner").setLevel(logging.CRITICAL)
    yield
    logging.getLogger("tmb.planner").setLevel(logging.WARNING)


def _extract_verdict(text: str) -> bool:
    from tmb.nodes.planner import _extract_verdict
    return _extract_verdict(text)


# ── Tier 1: JSON block ───────────────────────────────────────

def test_json_block_pass():
    text = '```json\n{"verdict": "PASS", "evidence": "file exists"}\n```'
    assert _extract_verdict(text) is True


def test_json_block_fail():
    text = '```json\n{"verdict": "FAIL", "evidence": "missing"}\n```'
    assert _extract_verdict(text) is False


def test_json_block_case_insensitive():
    text = '```json\n{"verdict": "pass", "evidence": "ok"}\n```'
    assert _extract_verdict(text) is True


# ── Tier 2: field pattern ────────────────────────────────────

def test_field_pattern_pass():
    text = 'The result is "verdict": "PASS" with notes.'
    assert _extract_verdict(text) is True


def test_field_pattern_fail():
    text = 'Result: "verdict": "FAIL" — missing file.'
    assert _extract_verdict(text) is False


# ── Tier 3: word-boundary keyword ────────────────────────────

def test_keyword_pass_standalone():
    text = "The task PASS — everything looks good."
    assert _extract_verdict(text) is True


def test_keyword_fail_standalone():
    text = "The validation result is FAIL due to missing output."
    assert _extract_verdict(text) is False


def test_password_should_not_match_pass():
    """'password' contains 'pass' but should NOT trigger a PASS verdict."""
    text = "Set the password to something secure."
    # No \bPASS\b match, no \bFAIL\b match → default FAIL
    assert _extract_verdict(text) is False


def test_passthrough_should_not_match_pass():
    """'passthrough' should NOT trigger a PASS verdict."""
    text = "Use passthrough mode for the proxy."
    assert _extract_verdict(text) is False


def test_bypass_should_not_match_fail():
    """'bypass' should NOT trigger a FAIL verdict via substring."""
    text = "You can bypass the cache for testing."
    # No \bPASS\b or \bFAIL\b → default FAIL
    assert _extract_verdict(text) is False


def test_both_pass_and_fail_first_wins():
    text = "PASS: most tests succeeded. One minor FAIL in edge case."
    assert _extract_verdict(text) is True


def test_both_fail_and_pass_first_wins():
    text = "FAIL: output missing. However PASS for secondary check."
    assert _extract_verdict(text) is False


# ── Tier 4: fail-closed default ──────────────────────────────

def test_empty_string_defaults_to_fail():
    assert _extract_verdict("") is False


def test_no_verdict_keyword_defaults_to_fail():
    text = "The task completed with some warnings."
    assert _extract_verdict(text) is False


def test_garbage_defaults_to_fail():
    text = "asdf 1234 !@#$"
    assert _extract_verdict(text) is False
