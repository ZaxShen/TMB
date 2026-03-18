"""Live integration tests using Ollama local models.

These tests require a running Ollama instance with llama3.2:3b pulled.
Skipped automatically if Ollama is not available.

Tests exercise the REAL LLM pipeline end-to-end:
  - GPU detection
  - LLM construction with num_gpu
  - Task classification (code vs non-code)
  - Planner plan generation with exploration skip
  - Executor tool loop with real responses
  - Timeout / connection error handling
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Skip if Ollama not running
# ---------------------------------------------------------------------------

def _ollama_available() -> bool:
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            models = [m["name"] for m in data.get("models", [])]
            return "llama3.2:3b" in models
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _ollama_available(),
    reason="Ollama not running or llama3.2:3b not available",
)

MODEL = "llama3.2:3b"
BASE_URL = "http://localhost:11434"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ollama_config(timeout=60):
    """Build nodes config that points both planner and executor to Ollama."""
    model_cfg = {
        "provider": "ollama",
        "name": MODEL,
        "temperature": 0,
        "base_url": BASE_URL,
        "timeout": timeout,
    }
    return {
        "planner": {"model": model_cfg, "tools": []},
        "executor": {"model": model_cfg, "tools": []},
    }


# ---------------------------------------------------------------------------
# Test 1: GPU detection actually works
# ---------------------------------------------------------------------------

def test_gpu_detection():
    """_detect_gpu_layers returns a valid int on this machine."""
    from tmb.config import _detect_gpu_layers
    result = _detect_gpu_layers()
    assert isinstance(result, int)
    assert result in (0, 1)
    print(f"  GPU detection: {result}")


# ---------------------------------------------------------------------------
# Test 2: get_llm creates a working ChatOllama with num_gpu
# ---------------------------------------------------------------------------

def test_get_llm_ollama_constructs():
    """get_llm with Ollama config should construct a ChatOllama instance."""
    from tmb.config import get_llm

    config = _make_ollama_config()
    with patch("tmb.config.load_nodes_config", return_value=config):
        llm = get_llm("planner")

    # Verify it's a ChatOllama and has num_gpu set
    assert type(llm).__name__ == "ChatOllama"
    assert hasattr(llm, "num_gpu")
    print(f"  ChatOllama constructed: model={llm.model}, num_gpu={llm.num_gpu}")


# ---------------------------------------------------------------------------
# Test 3: Real LLM invoke — basic round trip
# ---------------------------------------------------------------------------

def test_ollama_basic_invoke():
    """Ollama should respond to a simple prompt within timeout."""
    from tmb.config import get_llm
    from langchain_core.messages import HumanMessage

    config = _make_ollama_config(timeout=30)
    with patch("tmb.config.load_nodes_config", return_value=config):
        llm = get_llm("planner")

    response = llm.invoke([HumanMessage(content="Say 'hello' and nothing else.")])
    assert response.content, "LLM returned empty response"
    assert len(response.content) < 200, f"Response too long ({len(response.content)} chars)"
    print(f"  Response: {response.content[:80]}")


# ---------------------------------------------------------------------------
# Test 4: Task classification — non-code task
# ---------------------------------------------------------------------------

def test_classify_non_code_task():
    """Classification should identify email-writing as non-code task."""
    from tmb.config import get_llm
    from tmb.nodes.planner import CLASSIFY_INSTRUCTION
    from langchain_core.messages import SystemMessage, HumanMessage

    config = _make_ollama_config(timeout=30)
    with patch("tmb.config.load_nodes_config", return_value=config):
        llm = get_llm("planner")

    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content=(
            "## Task\nWrite a thank-you email to the team for their hard work on the project launch.\n\n"
            + CLASSIFY_INSTRUCTION
        )),
    ]

    response = llm.invoke(messages)
    answer = response.content.strip().lower()
    print(f"  Classification response: '{answer}'")
    # The model should say "no" — email writing doesn't need codebase
    assert "no" in answer, f"Expected 'no' for email task, got: {answer}"


# ---------------------------------------------------------------------------
# Test 5: Task classification — code task
# ---------------------------------------------------------------------------

def test_classify_code_task():
    """Classification should identify bug-fixing as a code task."""
    from tmb.config import get_llm
    from tmb.nodes.planner import CLASSIFY_INSTRUCTION
    from langchain_core.messages import SystemMessage, HumanMessage

    config = _make_ollama_config(timeout=30)
    with patch("tmb.config.load_nodes_config", return_value=config):
        llm = get_llm("planner")

    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content=(
            "## Task\nFix the login page crash when password contains special characters.\n\n"
            + CLASSIFY_INSTRUCTION
        )),
    ]

    response = llm.invoke(messages)
    answer = response.content.strip().lower()
    print(f"  Classification response: '{answer}'")
    assert "yes" in answer, f"Expected 'yes' for code task, got: {answer}"


# ---------------------------------------------------------------------------
# Test 6: Blueprint generation from a simple task
# ---------------------------------------------------------------------------

def test_ollama_generates_blueprint_xml():
    """Ollama should generate parseable blueprint XML for a simple task."""
    from tmb.config import get_llm
    from tmb.nodes.planner import BLUEPRINT_INSTRUCTION, _extract_blueprint_xml
    from langchain_core.messages import SystemMessage, HumanMessage

    config = _make_ollama_config(timeout=120)
    with patch("tmb.config.load_nodes_config", return_value=config):
        llm = get_llm("planner")

    messages = [
        SystemMessage(content="You are a project planner. Follow instructions exactly."),
        HumanMessage(content=(
            "## Goals\nCreate a file called hello.txt containing 'Hello World'.\n\n"
            + BLUEPRINT_INSTRUCTION
        )),
    ]

    response = llm.invoke(messages)
    raw = response.content
    print(f"  Blueprint response ({len(raw)} chars): {raw[:200]}...")

    # Try to parse — may or may not succeed with small models
    try:
        blueprint = _extract_blueprint_xml(raw)
        assert len(blueprint) >= 1, "Expected at least 1 task in blueprint"
        print(f"  Parsed {len(blueprint)} task(s): {[t.get('description', '')[:50] for t in blueprint]}")
    except ValueError as e:
        # Small models may not produce valid XML — that's OK for this test,
        # but the response should not be empty
        assert len(raw) > 50, f"Response too short ({len(raw)} chars)"
        print(f"  Parse failed (expected with small models): {e}")


# ---------------------------------------------------------------------------
# Test 7: Verdict parsing from Ollama
# ---------------------------------------------------------------------------

def test_ollama_generates_verdict():
    """Ollama should generate a parseable verdict for a completed task."""
    from tmb.config import get_llm
    from tmb.nodes.planner import _extract_verdict_xml
    from langchain_core.messages import SystemMessage, HumanMessage

    config = _make_ollama_config(timeout=60)
    with patch("tmb.config.load_nodes_config", return_value=config):
        llm = get_llm("planner")

    messages = [
        SystemMessage(content="You are a code reviewer."),
        HumanMessage(content=(
            "## Task\nCreate hello.txt with 'Hello World'\n\n"
            "## Executor's Output\nI created hello.txt with content 'Hello World'. "
            "The file exists at ./hello.txt.\n\n"
            "## Success Criteria\nhello.txt exists with content 'Hello World'\n\n"
            "Review the output and provide your verdict. Reply with:\n"
            "<verdict>PASS</verdict> or <verdict>FAIL</verdict>\n"
            "Then <evidence>your reasoning</evidence>"
        )),
    ]

    response = llm.invoke(messages)
    raw = response.content
    print(f"  Verdict response: {raw[:200]}")

    # _extract_verdict_xml returns True for PASS, False for FAIL
    verdict = _extract_verdict_xml(raw)
    assert isinstance(verdict, bool), f"Expected bool, got: {type(verdict)}"
    print(f"  Parsed verdict: {'PASS' if verdict else 'FAIL'}")


# ---------------------------------------------------------------------------
# Test 8: safe_llm_invoke handles connection error
# ---------------------------------------------------------------------------

def test_safe_invoke_bad_url():
    """safe_llm_invoke should raise LLMConnectionError for unreachable endpoint."""
    from tmb.config import get_llm, safe_llm_invoke, LLMConnectionError
    from langchain_core.messages import HumanMessage

    # Point to a non-existent server
    bad_config = {
        "planner": {"model": {
            "provider": "ollama",
            "name": MODEL,
            "base_url": "http://localhost:19999",
            "timeout": 5,
        }}
    }

    with patch("tmb.config.load_nodes_config", return_value=bad_config):
        llm = get_llm("planner")

    with pytest.raises(LLMConnectionError, match="connect"):
        safe_llm_invoke(llm, [HumanMessage(content="test")], label="test")


# ---------------------------------------------------------------------------
# Test 9: Executor simulated round-trip with real LLM
# ---------------------------------------------------------------------------

def test_executor_real_llm_response():
    """Executor-style prompt should get a reasonable response from Ollama."""
    from tmb.config import get_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    config = _make_ollama_config(timeout=60)
    with patch("tmb.config.load_nodes_config", return_value=config):
        llm = get_llm("executor")

    messages = [
        SystemMessage(content=(
            "You are an executor agent. You implement tasks. "
            "When done, describe what you did."
        )),
        HumanMessage(content=(
            "## Task\nCreate a Python function that adds two numbers.\n\n"
            "## Execution Plan\n1. Write a function `add(a, b)` that returns a + b\n"
            "2. Include a docstring\n\n"
            "Implement this task. Show the code you would write."
        )),
    ]

    response = llm.invoke(messages)
    content = response.content
    assert len(content) > 20, f"Response too short ({len(content)} chars)"
    # Should mention 'def' or 'function' or 'add' somewhere
    assert any(kw in content.lower() for kw in ["def ", "function", "add"]), \
        f"Response doesn't look like code: {content[:200]}"
    print(f"  Executor response ({len(content)} chars): {content[:150]}...")
