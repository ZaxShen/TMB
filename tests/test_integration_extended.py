"""Extended integration tests — multi-task pipeline and max-retry escalation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from langchain_core.messages import AIMessage
from tmb.store import Store


def _fake_ai_message(content: str) -> AIMessage:
    msg = AIMessage(content=content)
    msg.response_metadata = {
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    return msg


@pytest.fixture
def project_dir(tmp_path):
    cfg_dir = tmp_path / ".tmb" / "config"
    cfg_dir.mkdir(parents=True)
    docs_dir = tmp_path / "bro"
    docs_dir.mkdir()
    skills_dir = tmp_path / ".tmb" / "skills"
    skills_dir.mkdir(parents=True)

    (cfg_dir / "project.yaml").write_text(
        "name: test-project\nmax_retry_per_task: 2\n"
    )
    (docs_dir / "GOALS.md").write_text("# Goals\nBuild two features\n")
    return tmp_path


@pytest.fixture
def db_store(project_dir):
    db = project_dir / ".tmb" / "tmb.db"
    return Store(db_path=db)


def _make_patches(project_dir, db_store, fake_get_llm, max_retry=2):
    """Return context manager patches for executor + planner."""
    nodes_config = {
        "planner": {"model": {"provider": "anthropic", "name": "test"}, "tools": []},
        "executor": {"model": {"provider": "anthropic", "name": "test"}, "tools": []},
    }

    return (
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
        patch("tmb.nodes.planner.load_project_config",
              return_value={"max_retry_per_task": max_retry}),
        patch("tmb.nodes.planner.get_tools_for_node", return_value=[]),
        patch("tmb.nodes.planner.Store", return_value=db_store),
        patch("tmb.nodes.planner.docs_dir", return_value=project_dir / "bro"),
    )


# ── Multi-task pipeline ──────────────────────────────────────

def test_multi_task_pipeline(project_dir, db_store):
    """Two-task blueprint: both tasks should execute and pass sequentially."""

    issue_id = db_store.create_issue("Build two features")
    blueprint = [
        {
            "branch_id": "1",
            "description": "Create module A",
            "tools_required": ["file_write"],
            "skills_required": [],
            "success_criteria": "module_a.py exists",
        },
        {
            "branch_id": "2",
            "description": "Create module B",
            "tools_required": ["file_write"],
            "skills_required": [],
            "success_criteria": "module_b.py exists",
        },
    ]
    db_store.create_tasks(issue_id, blueprint)

    # Executor produces two different responses, validator always passes
    exec_responses = [
        _fake_ai_message("Created module_a.py."),
        _fake_ai_message("Created module_b.py."),
    ]
    val_responses = [
        _fake_ai_message('<verdict>PASS</verdict>\n<evidence>module_a.py exists</evidence>'),
        _fake_ai_message('<verdict>PASS</verdict>\n<evidence>module_b.py exists</evidence>'),
    ]

    exec_idx = {"i": 0}
    val_idx = {"i": 0}

    class FakeExecLLM:
        def invoke(self, messages, **kwargs):
            idx = min(exec_idx["i"], len(exec_responses) - 1)
            exec_idx["i"] += 1
            return exec_responses[idx]
        def bind_tools(self, tools):
            return self

    class FakeValLLM:
        def invoke(self, messages, **kwargs):
            idx = min(val_idx["i"], len(val_responses) - 1)
            val_idx["i"] += 1
            return val_responses[idx]
        def bind_tools(self, tools):
            return self

    def fake_get_llm(node_name):
        if node_name == "executor":
            return FakeExecLLM()
        return FakeValLLM()

    patches = _make_patches(project_dir, db_store, fake_get_llm)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], \
         patches[12], patches[13]:
        from tmb.engine import build_execution_graph

        graph = build_execution_graph()
        final_state = graph.invoke({
            "objective": "Build two features",
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
        })

    # Both tasks should have advanced
    assert final_state["current_task_idx"] == 2

    task1 = db_store.get_task_row(issue_id, "1")
    task2 = db_store.get_task_row(issue_id, "2")
    assert task1["status"] == "completed"
    assert task2["status"] == "completed"


# ── Escalation after max retries ─────────────────────────────

def test_escalation_after_max_retries(project_dir, db_store):
    """Task fails validation repeatedly → gets escalated after max_retry_per_task."""

    issue_id = db_store.create_issue("Hard task")
    blueprint = [
        {
            "branch_id": "1",
            "description": "Impossible task",
            "tools_required": [],
            "skills_required": [],
            "success_criteria": "never passes",
        },
    ]
    db_store.create_tasks(issue_id, blueprint)

    # Executor always produces output, validator always fails
    exec_resp = _fake_ai_message("Attempted the task.")
    fail_resp = _fake_ai_message(
        '<verdict>FAIL</verdict>\n<evidence>still broken</evidence>'
    )

    class FakeExecLLM:
        def invoke(self, messages, **kwargs):
            return exec_resp
        def bind_tools(self, tools):
            return self

    class FakeValLLM:
        def invoke(self, messages, **kwargs):
            return fail_resp
        def bind_tools(self, tools):
            return self

    def fake_get_llm(node_name):
        if node_name == "executor":
            return FakeExecLLM()
        return FakeValLLM()

    patches = _make_patches(project_dir, db_store, fake_get_llm, max_retry=2)

    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], \
         patches[6], patches[7], patches[8], patches[9], patches[10], patches[11], \
         patches[12], patches[13]:
        from tmb.engine import build_execution_graph

        graph = build_execution_graph()
        final_state = graph.invoke({
            "objective": "Hard task",
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
        })

    # Task should be escalated, not completed
    task = db_store.get_task_row(issue_id, "1")
    assert task["status"] in ("escalated", "failed")

    # Should have multiple verdict_fail events
    ledger = db_store.get_ledger(issue_id)
    fail_events = [e for e in ledger if e["event_type"] == "verdict_fail"]
    assert len(fail_events) >= 2


# ── Engine graph structure ────────────────────────────────────

def test_execution_graph_has_expected_nodes():
    """build_execution_graph should contain executor and planner_validate nodes."""
    from tmb.engine import build_execution_graph

    graph = build_execution_graph()
    # LangGraph compiled graphs expose nodes dict
    node_names = set(graph.get_graph().nodes.keys())

    assert "executor" in node_names
    assert "planner_validate" in node_names


def test_full_graph_has_expected_nodes():
    """build_graph should contain planner_plan and the execution nodes."""
    from tmb.engine import build_graph

    graph = build_graph()
    node_names = set(graph.get_graph().nodes.keys())

    assert "planner_plan" in node_names
    assert "executor" in node_names
    assert "planner_validate" in node_names
