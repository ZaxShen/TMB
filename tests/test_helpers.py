"""Tests for planner helper functions — JSON extraction and verdict parsing."""

from __future__ import annotations

import pytest

from tmb.nodes.planner import _extract_json_array, _extract_verdict


class TestExtractJsonArray:
    def test_raw_json(self):
        result = _extract_json_array('[{"id": 1}, {"id": 2}]')
        assert len(result) == 2
        assert result[0]["id"] == 1

    def test_json_in_markdown_fence(self):
        raw = '```json\n[{"branch_id": "1", "description": "do stuff"}]\n```'
        result = _extract_json_array(raw)
        assert len(result) == 1
        assert result[0]["branch_id"] == "1"

    def test_json_in_plain_fence(self):
        raw = '```\n[{"a": 1}]\n```'
        result = _extract_json_array(raw)
        assert result == [{"a": 1}]

    def test_json_with_preamble(self):
        raw = 'Here is the blueprint:\n[{"task": "build"}]'
        result = _extract_json_array(raw)
        assert result == [{"task": "build"}]

    def test_malformed_raises(self):
        with pytest.raises(Exception):
            _extract_json_array("this is not json at all")


class TestExtractVerdict:
    def test_json_block_pass(self):
        text = '```json\n{"verdict": "PASS", "evidence": "all good"}\n```'
        assert _extract_verdict(text) is True

    def test_json_block_fail(self):
        text = '```json\n{"verdict": "FAIL", "failure_details": "broken"}\n```'
        assert _extract_verdict(text) is False

    def test_inline_field_pass(self):
        text = 'The result is "verdict": "PASS" because tests passed.'
        assert _extract_verdict(text) is True

    def test_keyword_pass(self):
        assert _extract_verdict("All checks PASS.") is True

    def test_keyword_fail(self):
        assert _extract_verdict("The test FAIL due to missing output.") is False

    def test_both_keywords_first_wins(self):
        assert _extract_verdict("PASS — all good, no FAIL") is True
        assert _extract_verdict("FAIL — broken, not a PASS") is False

    def test_no_verdict_defaults_to_fail(self):
        assert _extract_verdict("unclear result") is False
