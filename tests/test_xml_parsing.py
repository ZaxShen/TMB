"""Tests for XML-based parsing functions."""

from __future__ import annotations

import pytest


class TestExtractBlueprintXml:

    def _extract(self, raw: str) -> list[dict]:
        from tmb.nodes.planner import _extract_blueprint_xml
        return _extract_blueprint_xml(raw)

    def test_bare_xml(self):
        """Normal XML output without code fences."""
        raw = (
            "<blueprint>\n"
            "  <task>\n"
            "    <branch_id>1</branch_id>\n"
            "    <description>Create module A</description>\n"
            "    <tools_required>shell,file_write</tools_required>\n"
            "    <skills_required>db-operations</skills_required>\n"
            "    <success_criteria>module_a.py exists</success_criteria>\n"
            "  </task>\n"
            "</blueprint>"
        )
        result = self._extract(raw)
        assert len(result) == 1
        assert result[0]["branch_id"] == "1"
        assert result[0]["description"] == "Create module A"
        assert result[0]["tools_required"] == ["shell", "file_write"]
        assert result[0]["skills_required"] == ["db-operations"]
        assert result[0]["success_criteria"] == "module_a.py exists"

    def test_xml_in_xml_fence(self):
        """XML wrapped in ```xml code fence."""
        raw = '```xml\n<blueprint><task><branch_id>1</branch_id><description>Do stuff</description><tools_required>shell</tools_required><skills_required></skills_required><success_criteria>works</success_criteria></task></blueprint>\n```'
        result = self._extract(raw)
        assert len(result) == 1
        assert result[0]["branch_id"] == "1"

    def test_xml_in_bare_fence(self):
        """XML wrapped in bare ``` code fence."""
        raw = '```\n<blueprint><task><branch_id>2</branch_id><description>Build it</description><tools_required></tools_required><skills_required></skills_required><success_criteria>done</success_criteria></task></blueprint>\n```'
        result = self._extract(raw)
        assert len(result) == 1
        assert result[0]["branch_id"] == "2"

    def test_xml_with_prose_preamble(self):
        """XML preceded by explanatory prose."""
        raw = (
            "Here is the blueprint based on my analysis:\n\n"
            "<blueprint>\n"
            "  <task>\n"
            "    <branch_id>1</branch_id>\n"
            "    <description>Implement feature</description>\n"
            "    <tools_required>shell</tools_required>\n"
            "    <skills_required></skills_required>\n"
            "    <success_criteria>tests pass</success_criteria>\n"
            "  </task>\n"
            "</blueprint>"
        )
        result = self._extract(raw)
        assert len(result) == 1
        assert result[0]["description"] == "Implement feature"

    def test_multiple_tasks(self):
        """Blueprint with multiple tasks."""
        raw = (
            "<blueprint>\n"
            "  <task>\n"
            "    <branch_id>1</branch_id>\n"
            "    <description>First task</description>\n"
            "    <tools_required>shell</tools_required>\n"
            "    <skills_required></skills_required>\n"
            "    <success_criteria>first done</success_criteria>\n"
            "  </task>\n"
            "  <task>\n"
            "    <branch_id>2</branch_id>\n"
            "    <description>Second task</description>\n"
            "    <tools_required>file_write</tools_required>\n"
            "    <skills_required>csv-handling</skills_required>\n"
            "    <success_criteria>second done</success_criteria>\n"
            "  </task>\n"
            "</blueprint>"
        )
        result = self._extract(raw)
        assert len(result) == 2
        assert result[0]["branch_id"] == "1"
        assert result[1]["branch_id"] == "2"

    def test_empty_tools_and_skills(self):
        """Empty tools_required and skills_required become empty lists."""
        raw = (
            "<blueprint><task>"
            "<branch_id>1</branch_id>"
            "<description>Simple task</description>"
            "<tools_required></tools_required>"
            "<skills_required></skills_required>"
            "<success_criteria>done</success_criteria>"
            "</task></blueprint>"
        )
        result = self._extract(raw)
        assert result[0]["tools_required"] == []
        assert result[0]["skills_required"] == []

    def test_description_with_code_fences(self):
        """Description containing markdown code fences — the key bug that broke JSON parsing."""
        raw = (
            "<blueprint><task>"
            "<branch_id>1</branch_id>"
            "<description>Create a script that prints hello:\n"
            "```python\nprint('hello')\n```\n"
            "Save it as hello.py</description>"
            "<tools_required>shell,file_write</tools_required>"
            "<skills_required></skills_required>"
            "<success_criteria>hello.py runs</success_criteria>"
            "</task></blueprint>"
        )
        result = self._extract(raw)
        assert len(result) == 1
        assert "```python" in result[0]["description"]
        assert result[0]["branch_id"] == "1"

    def test_description_with_ampersand(self):
        """Description containing & character — must be handled without XML parse error."""
        raw = (
            "<blueprint><task>"
            "<branch_id>1</branch_id>"
            "<description>Read input & write output</description>"
            "<tools_required>shell</tools_required>"
            "<skills_required></skills_required>"
            "<success_criteria>done</success_criteria>"
            "</task></blueprint>"
        )
        result = self._extract(raw)
        assert "&" in result[0]["description"]

    def test_tools_with_whitespace(self):
        """Comma-separated tools with extra whitespace."""
        raw = (
            "<blueprint><task>"
            "<branch_id>1</branch_id>"
            "<description>task</description>"
            "<tools_required> shell , file_write , search </tools_required>"
            "<skills_required></skills_required>"
            "<success_criteria>done</success_criteria>"
            "</task></blueprint>"
        )
        result = self._extract(raw)
        assert result[0]["tools_required"] == ["shell", "file_write", "search"]

    def test_malformed_xml_raises_valueerror(self):
        """Completely non-XML input raises ValueError."""
        with pytest.raises(ValueError):
            from tmb.nodes.planner import _extract_blueprint_xml
            _extract_blueprint_xml("this is not xml at all, just plain text")

    def test_malformed_xml_logs_warning(self, caplog):
        """Malformed input should log a warning with diagnostics."""
        import logging
        with caplog.at_level(logging.WARNING, logger="tmb.planner"):
            with pytest.raises(ValueError):
                self._extract("this is not xml at all, just plain text")
        assert any("Blueprint XML parse failed" in r.message for r in caplog.records)

    def test_truncated_output_recovers_complete_tasks(self):
        """Truncated output should recover all complete tasks before the cutoff."""
        raw = (
            "<blueprint>\n"
            "  <task>\n"
            "    <branch_id>1</branch_id>\n"
            "    <description>First task - complete</description>\n"
            "    <tools_required>shell</tools_required>\n"
            "    <skills_required></skills_required>\n"
            "    <success_criteria>first done</success_criteria>\n"
            "  </task>\n"
            "  <task>\n"
            "    <branch_id>2</branch_id>\n"
            "    <description>Second task - complete</description>\n"
            "    <tools_required>file_write</tools_required>\n"
            "    <skills_required></skills_required>\n"
            "    <success_criteria>second done</success_criteria>\n"
            "  </task>\n"
            "  <task>\n"
            "    <branch_id>3</branch_id>\n"
            "    <description>Third task that got trun"
        )
        result = self._extract(raw)
        assert len(result) == 2
        assert result[0]["branch_id"] == "1"
        assert result[1]["branch_id"] == "2"

    def test_truncated_output_zero_complete_tasks(self):
        """Truncated output with no complete tasks should raise ValueError."""
        raw = (
            "<blueprint>\n"
            "  <task>\n"
            "    <branch_id>1</branch_id>\n"
            "    <description>Only task, incomple"
        )
        with pytest.raises(ValueError):
            self._extract(raw)

    def test_truncated_output_logs_recovery(self, caplog):
        """Truncation recovery should log a warning."""
        import logging
        raw = (
            "<blueprint>\n"
            "  <task>\n"
            "    <branch_id>1</branch_id>\n"
            "    <description>Complete task</description>\n"
            "    <tools_required>shell</tools_required>\n"
            "    <skills_required></skills_required>\n"
            "    <success_criteria>done</success_criteria>\n"
            "  </task>\n"
            "  <task>\n"
            "    <branch_id>2</branch_id>\n"
            "    <description>Truncat"
        )
        with caplog.at_level(logging.WARNING, logger="tmb.planner"):
            result = self._extract(raw)
        assert len(result) == 1
        assert any("Recovered" in r.message for r in caplog.records)

    def test_normal_output_no_recovery_needed(self):
        """Normal complete output should work without triggering recovery."""
        raw = (
            "<blueprint>\n"
            "  <task>\n"
            "    <branch_id>1</branch_id>\n"
            "    <description>Normal task</description>\n"
            "    <tools_required>shell</tools_required>\n"
            "    <skills_required></skills_required>\n"
            "    <success_criteria>done</success_criteria>\n"
            "  </task>\n"
            "</blueprint>"
        )
        result = self._extract(raw)
        assert len(result) == 1
        # No recovery was needed — normal path


class TestExtractVerdictXml:

    def _extract(self, text: str) -> bool:
        from tmb.nodes.planner import _extract_verdict_xml
        return _extract_verdict_xml(text)

    def test_xml_pass(self):
        assert self._extract("<verdict>PASS</verdict>") is True

    def test_xml_fail(self):
        assert self._extract("<verdict>FAIL</verdict>") is False

    def test_xml_case_insensitive(self):
        assert self._extract("<verdict>pass</verdict>") is True
        assert self._extract("<verdict>Fail</verdict>") is False

    def test_xml_with_whitespace(self):
        assert self._extract("<verdict> PASS </verdict>") is True

    def test_xml_with_surrounding_prose(self):
        text = "After checking everything:\n\n<verdict>PASS</verdict>\n\nAll tests passed."
        assert self._extract(text) is True

    def test_evidence_with_braces(self):
        """Evidence text containing {x} — broke the old JSON regex."""
        text = "<evidence>Found {count} items in output</evidence>\n<verdict>PASS</verdict>"
        assert self._extract(text) is True

    def test_fail_keyword_before_pass_verdict(self):
        """LLM says 'not a FAIL' but verdict is PASS — XML tag is authoritative."""
        text = "This is not a FAIL. Everything works.\n<verdict>PASS</verdict>"
        assert self._extract(text) is True

    def test_pass_keyword_before_fail_verdict(self):
        """LLM mentions PASS in prose but verdict is FAIL — XML tag is authoritative."""
        text = "While the PASS rate was high, critical tests broke.\n<verdict>FAIL</verdict>"
        assert self._extract(text) is False

    def test_tool_output_json_before_verdict(self):
        """Tool output containing JSON before the actual verdict — broke old parser."""
        text = (
            'Tool output: {"status": "ok", "verdict": "PASS", "count": 5}\n\n'
            "But the actual task failed.\n<verdict>FAIL</verdict>"
        )
        assert self._extract(text) is False

    def test_both_keywords_no_xml_last_wins(self):
        """Keyword fallback: when both PASS and FAIL appear, LAST one wins."""
        assert self._extract("PASS initially but ended in FAIL") is False
        assert self._extract("First FAIL then corrected to PASS") is True

    def test_keyword_only_pass(self):
        """No XML tags, only keyword PASS."""
        assert self._extract("The task PASS — everything looks good.") is True

    def test_keyword_only_fail(self):
        """No XML tags, only keyword FAIL."""
        assert self._extract("The validation result is FAIL due to missing output.") is False

    def test_password_not_match(self):
        """'password' should NOT trigger PASS."""
        assert self._extract("Set the password to something secure.") is False

    def test_empty_string(self):
        assert self._extract("") is False

    def test_no_verdict_defaults_to_fail(self):
        assert self._extract("The task completed with some warnings.") is False

    def test_garbage_defaults_to_fail(self):
        assert self._extract("asdf 1234 !@#$") is False

    def test_keyword_fallback_logs_warning(self, caplog):
        """Keyword fallback should log a warning."""
        import logging
        with caplog.at_level(logging.WARNING, logger="tmb.planner"):
            result = self._extract("The task PASS — everything good.")
        assert result is True
        assert any("fell back to keyword match" in r.message for r in caplog.records)

    def test_no_verdict_logs_warning(self, caplog):
        """No verdict at all should log a warning."""
        import logging
        with caplog.at_level(logging.WARNING, logger="tmb.planner"):
            result = self._extract("some random text with no verdict")
        assert result is False
        assert any("No verdict extracted" in r.message for r in caplog.records)


class TestDetectEscalationXml:

    def _detect(self, content) -> bool:
        from tmb.nodes.executor import _detect_escalation
        return _detect_escalation(content)

    def test_xml_status_escalate(self):
        text = "I cannot complete this.\n<status>escalate</status>\n<escalation_reason>missing API key</escalation_reason>"
        assert self._detect(text) is True

    def test_xml_status_escalate_case(self):
        assert self._detect("<status>Escalate</status>") is True

    def test_xml_status_escalate_whitespace(self):
        assert self._detect("<status> escalate </status>") is True

    def test_xml_status_completed(self):
        assert self._detect("<status>completed</status>") is False

    def test_xml_with_nested_context(self):
        """Nested XML context — the bug that broke old JSON regex."""
        text = (
            "<status>escalate</status>\n"
            "<escalation_reason>blocked</escalation_reason>\n"
            "<context><detail>missing credentials</detail></context>"
        )
        assert self._detect(text) is True

    def test_keyword_escalate_in_prose(self):
        """Keyword fallback: 'escalate' in prose without XML tags."""
        text = "I need to escalate this task because the file is corrupted."
        assert self._detect(text) is True

    def test_keyword_escalate_uppercase(self):
        text = "ESCALATE: Cannot proceed without database credentials."
        assert self._detect(text) is True

    def test_no_escalation_normal_output(self):
        text = "Task completed successfully. All files created."
        assert self._detect(text) is False

    def test_empty_string(self):
        assert self._detect("") is False

    def test_escalated_past_tense_not_detected(self):
        """'escalated' has a 'd' after 'escalate' — \\bescalate\\b doesn't match."""
        text = "The previous task was escalated."
        assert self._detect(text) is False

    def test_list_content_normalized(self):
        """Anthropic sometimes returns content as list of blocks."""
        content = [{"text": "I need to "}, {"text": "escalate this."}]
        assert self._detect(content) is True

    def test_list_content_no_escalation(self):
        content = [{"text": "Task "}, {"text": "completed successfully."}]
        assert self._detect(content) is False

    def test_keyword_fallback_logs_info(self, caplog):
        """Keyword escalation fallback should log at INFO level."""
        import logging
        with caplog.at_level(logging.INFO, logger="tmb.executor"):
            result = self._detect("I need to escalate this task.")
        assert result is True
        assert any("keyword fallback" in r.message for r in caplog.records)
