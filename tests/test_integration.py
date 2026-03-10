"""Integration test — full executor → validate pipeline with mocked LLM.

Exercises the real Store, Engine, Executor node, Planner validate node,
state transitions, permissions, and token tracking wiring.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from langchain_core.messages import AIMessage
from baymax.store import Store


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
    cfg_dir = tmp_path / ".baymax" / "config"
    cfg_dir.mkdir(parents=True)
    docs_dir = tmp_path / "baymax-docs"
    docs_dir.mkdir()
    skills_dir = tmp_path / ".baymax" / "skills"
    skills_dir.mkdir(parents=True)

    (cfg_dir / "project.yaml").write_text(
        "name: test-project\ntest_command: pytest\nmax_retry_per_task: 3\n"
    )

    (docs_dir / "GOALS.md").write_text("# Goals\nCreate hello.txt with 'Hello World'\n")

    return tmp_path


@pytest.fixture
def db_store(project_dir):
    """Store backed by a temp DB inside the fake project."""
    db = project_dir / ".baymax" / "baymax.db"
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
        '```json\n{"verdict": "PASS", "evidence": "hello.txt exists"}\n```'
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

    db_path = project_dir / ".baymax" / "baymax.db"

    with (
        patch("baymax.nodes.executor.get_llm", side_effect=fake_get_llm),
        patch("baymax.nodes.executor.load_prompt", return_value="You are an executor."),
        patch("baymax.nodes.executor.load_nodes_config", return_value=nodes_config),
        patch("baymax.nodes.executor.get_project_root", return_value=project_dir),
        patch("baymax.nodes.executor.get_tools_for_node", return_value=[]),
        patch("baymax.nodes.executor.Store", return_value=db_store),

        patch("baymax.nodes.planner.get_llm", side_effect=fake_get_llm),
        patch("baymax.nodes.planner.load_prompt", return_value="You are a planner."),
        patch("baymax.nodes.planner.load_nodes_config", return_value=nodes_config),
        patch("baymax.nodes.planner.get_project_root", return_value=project_dir),
        patch("baymax.nodes.planner.load_project_config", return_value={"max_retry_per_task": 3}),
        patch("baymax.nodes.planner.get_tools_for_node", return_value=[]),
        patch("baymax.nodes.planner.Store", return_value=db_store),
        patch("baymax.nodes.planner.docs_dir", return_value=project_dir / "baymax-docs"),
    ):
        from baymax.engine import build_execution_graph

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
