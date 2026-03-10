"""Tests for baymax.store — SQLite audit store."""

from __future__ import annotations


def test_issue_lifecycle(store):
    issue_id = store.create_issue("Build a widget")
    issue = store.get_issue(issue_id)

    assert issue is not None
    assert issue["objective"] == "Build a widget"
    assert issue["status"] == "open"

    store.close_issue(issue_id, "completed")
    issue = store.get_issue(issue_id)
    assert issue["status"] == "completed"


def test_task_crud(store):
    issue_id = store.create_issue("Task CRUD test")
    blueprint = [
        {
            "branch_id": "1",
            "description": "Create module",
            "tools_required": ["shell"],
            "skills_required": [],
            "success_criteria": "Module exists",
        },
        {
            "branch_id": "2",
            "description": "Write tests",
            "tools_required": ["file_write"],
            "skills_required": [],
            "success_criteria": "Tests pass",
        },
    ]
    store.create_tasks(issue_id, blueprint)

    tasks = store.get_tasks(issue_id)
    assert len(tasks) == 2
    assert tasks[0]["branch_id"] == "1"
    assert tasks[0]["status"] == "pending"

    store.update_task_status(issue_id, "1", "completed")
    task = store.get_task_row(issue_id, "1")
    assert task["status"] == "completed"


def test_token_tracking(store):
    issue_id = store.create_issue("Token test")

    store.log_tokens(issue_id, "planner", 1000, 200)
    store.log_tokens(issue_id, "planner", 500, 100)
    store.log_tokens(issue_id, "executor", 800, 150)

    summary = store.get_token_summary(issue_id)
    assert summary["planner"]["in"] == 1500
    assert summary["planner"]["out"] == 300
    assert summary["executor"]["in"] == 800
    assert summary["executor"]["out"] == 150
    assert summary["total"]["in"] == 2300
    assert summary["total"]["out"] == 450


def test_ledger_and_has_event(store):
    issue_id = store.create_issue("Ledger test")

    store.log(issue_id, None, "planner", "flowchart_generated", {},
              summary="Generated FLOWCHART.md")
    store.log(issue_id, "1", "executor", "task_executed", {"output": "ok"},
              summary="Ran task 1")

    assert store.has_event(issue_id, "flowchart_generated") is True
    assert store.has_event(issue_id, "nonexistent_event") is False

    ledger = store.get_ledger(issue_id)
    assert len(ledger) == 3  # issue_opened + 2 explicit logs

    branch_events = store.get_ledger(issue_id, branch_id="1")
    assert len(branch_events) == 1
    assert branch_events[0]["event_type"] == "task_executed"


def test_report_includes_tokens(store):
    issue_id = store.create_issue("Report test")
    store.log_tokens(issue_id, "planner", 500, 100)

    md = store.export_report_md(issue_id)
    assert "## Token Usage" in md
    assert "planner" in md
    assert "500" in md
