"""Tests for planner helper functions — JSON extraction and verdict parsing."""

from __future__ import annotations

import pytest

from tmb.nodes.planner import _extract_blueprint_xml, _extract_verdict_xml


class TestExtractBlueprintXml:
    def test_bare_xml(self):
        raw = "<blueprint><task><branch_id>1</branch_id><description>do stuff</description><tools_required>shell</tools_required><skills_required></skills_required><success_criteria>works</success_criteria></task></blueprint>"
        result = _extract_blueprint_xml(raw)
        assert len(result) == 1
        assert result[0]["branch_id"] == "1"

    def test_xml_in_fence(self):
        raw = '```xml\n<blueprint><task><branch_id>1</branch_id><description>do stuff</description><tools_required></tools_required><skills_required></skills_required><success_criteria>works</success_criteria></task></blueprint>\n```'
        result = _extract_blueprint_xml(raw)
        assert len(result) == 1
        assert result[0]["branch_id"] == "1"

    def test_xml_in_bare_fence(self):
        raw = '```\n<blueprint><task><branch_id>1</branch_id><description>build</description><tools_required></tools_required><skills_required></skills_required><success_criteria>done</success_criteria></task></blueprint>\n```'
        result = _extract_blueprint_xml(raw)
        assert result[0]["description"] == "build"

    def test_xml_with_preamble(self):
        raw = 'Here is the blueprint:\n<blueprint><task><branch_id>1</branch_id><description>build</description><tools_required></tools_required><skills_required></skills_required><success_criteria>done</success_criteria></task></blueprint>'
        result = _extract_blueprint_xml(raw)
        assert result == [{"branch_id": "1", "description": "build", "tools_required": [], "skills_required": [], "success_criteria": "done"}]

    def test_malformed_raises(self):
        with pytest.raises(ValueError):
            _extract_blueprint_xml("this is not xml at all")


class TestExtractVerdictXml:
    def test_xml_tag_pass(self):
        text = "All verified.\n<verdict>PASS</verdict>\n<evidence>tests pass</evidence>"
        assert _extract_verdict_xml(text) is True

    def test_xml_tag_fail(self):
        text = "<verdict>FAIL</verdict>\n<failure_details>output missing</failure_details>"
        assert _extract_verdict_xml(text) is False

    def test_inline_xml_pass(self):
        text = "Result: <verdict>PASS</verdict> with notes."
        assert _extract_verdict_xml(text) is True

    def test_keyword_pass(self):
        assert _extract_verdict_xml("All checks PASS.") is True

    def test_keyword_fail(self):
        assert _extract_verdict_xml("The test FAIL due to missing output.") is False

    def test_both_keywords_last_wins(self):
        assert _extract_verdict_xml("PASS initially but then FAIL") is False
        assert _extract_verdict_xml("FAIL at first but ultimately PASS") is True

    def test_no_verdict_defaults_to_fail(self):
        assert _extract_verdict_xml("unclear result") is False
