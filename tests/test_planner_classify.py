"""Tests for task classification gate in planner."""
import pytest


def test_classify_instruction_exists():
    """CLASSIFY_INSTRUCTION constant should be defined."""
    from tmb.nodes.planner import CLASSIFY_INSTRUCTION
    assert "yes" in CLASSIFY_INSTRUCTION.lower()
    assert "no" in CLASSIFY_INSTRUCTION.lower()
    assert "email" in CLASSIFY_INSTRUCTION.lower()  # listed as a NO example


def test_classify_instruction_has_examples():
    """Classification instruction should contain both code and non-code examples."""
    from tmb.nodes.planner import CLASSIFY_INSTRUCTION
    assert "bug" in CLASSIFY_INSTRUCTION.lower()
    assert "email" in CLASSIFY_INSTRUCTION.lower()
    assert "feature" in CLASSIFY_INSTRUCTION.lower()
    assert "document" in CLASSIFY_INSTRUCTION.lower()
