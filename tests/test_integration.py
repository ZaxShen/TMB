"""Integration test — full executor → validate pipeline with mocked LLM.

Exercises the real Store, Engine, Executor node, Planner validate node,
state transitions, permissions, and token tracking wiring.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from langchain_core.messages import AIMessage
from tmb.store import Store


def _fake_ai_message(content: str) -> AIMessage:
    """Create a real AIMessage with fake token usage metadata."""
    msg = AIMessage(content=content)
    msg.response_metadata = {
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return msg


class FakeLLM:
    """Returns canned AIMessage responses based on call order."""

    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)
        self._call_idx = 0

    def invoke(self, messages, **kwargs):
        resp = self._responses[min(self._call_idx, len(self._responses) - 1)]
        self._call_idx += 1
        return resp

    def bind_tools(self, tools):
        return self


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_dir(tmp_path):
    """Set up a minimal project directory with required config and docs."""
    cfg_dir = tmp_path / ".tmb" / "config"
    cfg_dir.mkdir(parents=True)
    docs_dir = tmp_path / "bro"
    docs_dir.mkdir()
    skills_dir = tmp_path / ".tmb" / "skills"
    skills_dir.mkdir(parents=True)

    (cfg_dir / "project.yaml").write_text(
        "name: test-project\nmax_retry_per_task: 3\n"
    )

    (docs_dir / "GOALS.md").write_text("# Goals\nCreate hello.txt with 'Hello World'\n")

    return tmp_path


@pytest.fixture
def db_store(project_dir):
    """Store backed by a temp DB inside the fake project."""
    db = project_dir / ".tmb" / "tmb.db"
    return Store(db_path=db)


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

def test_executor_validate_pipeline(project_dir, db_store):
    """Full pipeline: executor runs a task, planner_validate passes it."""

    issue_id = db_store.create_issue("Create hello.txt")
    blueprint = [
        {
            "branch_id": "1",
            "description": "Create hello.txt with Hello World",
            "tools_required": ["file_write"],
            "skills_required": [],
            "success_criteria": "hello.txt exists with content 'Hello World'",
        },
    ]
    db_store.create_tasks(issue_id, blueprint)

    executor_response = _fake_ai_message(
        "Created hello.txt with 'Hello World'. Task complete."
    )
    validate_response = _fake_ai_message(
        '<verdict>PASS</verdict>\n<evidence>hello.txt exists</evidence>'
    )

    executor_llm = FakeLLM([executor_response])
    validate_llm = FakeLLM([validate_response])

    call_count = {"n": 0}

    def fake_get_llm(node_name):
        call_count["n"] += 1
        if node_name == "executor":
            return executor_llm
        return validate_llm

    nodes_config = {
        "planner": {"model": {"provider": "anthropic", "name": "test"}, "tools": []},
        "executor": {"model": {"provider": "anthropic", "name": "test"}, "tools": []},
    }

    db_path = project_dir / ".tmb" / "tmb.db"

    with (
        patch("tmb.nodes.executor.get_llm", side_effect=fake_get_llm),
        patch("tmb.nodes.executor.load_prompt", return_value="You are an executor."),
        patch("tmb.nodes.executor.load_nodes_config", return_value=nodes_config),
        patch("tmb.nodes.executor.get_project_root", return_value=project_dir),
        patch("tmb.nodes.executor.get_tools_for_node", return_value=[]),
        patch("tmb.nodes.executor.Store", return_value=db_store),

        patch("tmb.nodes.planner.get_llm", side_effect=fake_get_llm),
        patch("tmb.nodes.planner.load_prompt", return_value="You are a planner."),
        patch("tmb.nodes.planner.load_nodes_config", return_value=nodes_config),
        patch("tmb.nodes.planner.get_project_root", return_value=project_dir),
        patch("tmb.nodes.planner.load_project_config", return_value={"max_retry_per_task": 3}),
        patch("tmb.nodes.planner.get_tools_for_node", return_value=[]),
        patch("tmb.nodes.planner.Store", return_value=db_store),
        patch("tmb.nodes.planner.docs_dir", return_value=project_dir / "bro"),
    ):
        from tmb.engine import build_execution_graph

        graph = build_execution_graph()

        initial_state = {
            "objective": "Create hello.txt",
            "project_context": "",
            "discussion": "",
            "issue_id": issue_id,
            "blueprint": blueprint,
            "current_task_idx": 0,
            "execution_log": "",
            "review_feedback": "",
            "iteration_count": 0,
            "messages": [],
            "next_node": "",
        }

        final_state = graph.invoke(initial_state)

    assert final_state["current_task_idx"] == 1

    task = db_store.get_task_row(issue_id, "1")
    assert task["status"] == "completed"

    assert db_store.has_event(issue_id, "task_executed")
    assert db_store.has_event(issue_id, "verdict_pass")

    summary = db_store.get_token_summary(issue_id)
    assert summary["total"]["in"] > 0
    assert summary["total"]["out"] > 0


def test_fail_retry_pass_pipeline(project_dir, db_store):
    """Pipeline: executor runs → validate FAILs → retry → validate PASSes."""

    issue_id = db_store.create_issue("Fix the bug")
    blueprint = [
        {
            "branch_id": "1",
            "description": "Fix the bug in main.py",
            "tools_required": ["file_write"],
            "skills_required": [],
            "success_criteria": "bug is fixed and tests pass",
        },
    ]
    db_store.create_tasks(issue_id, blueprint)

    executor_resp_1 = _fake_ai_message("Attempted fix.")
    fail_response = _fake_ai_message(
        '<verdict>FAIL</verdict>\n<evidence>tests still failing</evidence>'
    )
    executor_resp_2 = _fake_ai_message("Applied correct fix.")
    pass_response = _fake_ai_message(
        '<verdict>PASS</verdict>\n<evidence>all tests pass</evidence>'
    )

    executor_responses = [executor_resp_1, executor_resp_2]
    validate_responses = [fail_response, pass_response]

    exec_idx = {"i": 0}
    val_idx = {"i": 0}

    class FakeExecLLM:
        def invoke(self, messages, **kwargs):
            idx = min(exec_idx["i"], len(executor_responses) - 1)
            exec_idx["i"] += 1
            return executor_responses[idx]
        def bind_tools(self, tools):
            return self

    class FakeValLLM:
        def invoke(self, messages, **kwargs):
            idx = min(val_idx["i"], len(validate_responses) - 1)
            val_idx["i"] += 1
            return validate_responses[idx]
        def bind_tools(self, tools):
            return self

    def fake_get_llm(node_name):
        if node_name == "executor":
            return FakeExecLLM()
        return FakeValLLM()

    nodes_config = {
        "planner": {"model": {"provider": "anthropic", "name": "test"}, "tools": []},
        "executor": {"model": {"provider": "anthropic", "name": "test"}, "tools": []},
    }

    with (
        patch("tmb.nodes.executor.get_llm", side_effect=fake_get_llm),
        patch("tmb.nodes.executor.load_prompt", return_value="You are an executor."),
        patch("tmb.nodes.executor.load_nodes_config", return_value=nodes_config),
        patch("tmb.nodes.executor.get_project_root", return_value=project_dir),
        patch("tmb.nodes.executor.get_tools_for_node", return_value=[]),
        patch("tmb.nodes.executor.Store", return_value=db_store),

        patch("tmb.nodes.planner.get_llm", side_effect=fake_get_llm),
        patch("tmb.nodes.planner.load_prompt", return_value="You are a planner."),
        patch("tmb.nodes.planner.load_nodes_config", return_value=nodes_config),
        patch("tmb.nodes.planner.get_project_root", return_value=project_dir),
        patch("tmb.nodes.planner.load_project_config", return_value={"max_retry_per_task": 3}),
        patch("tmb.nodes.planner.get_tools_for_node", return_value=[]),
        patch("tmb.nodes.planner.Store", return_value=db_store),
        patch("tmb.nodes.planner.docs_dir", return_value=project_dir / "bro"),
    ):
        from tmb.engine import build_execution_graph

        graph = build_execution_graph()

        initial_state = {
            "objective": "Fix the bug",
            "project_context": "",
            "discussion": "",
            "issue_id": issue_id,
            "blueprint": blueprint,
            "current_task_idx": 0,
            "execution_log": "",
            "review_feedback": "",
            "iteration_count": 0,
            "replan_count": 0,
            "messages": [],
            "next_node": "",
        }

        final_state = graph.invoke(initial_state)

    assert final_state["current_task_idx"] == 1
    task = db_store.get_task_row(issue_id, "1")
    assert task["status"] == "completed"
    assert db_store.has_event(issue_id, "verdict_fail")
    assert db_store.has_event(issue_id, "verdict_pass")
