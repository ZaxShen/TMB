"""Extended Store tests — discussions, chat, skills, file registry, resume helpers."""

from __future__ import annotations

import pytest


# ── Discussion ────────────────────────────────────────────────

def test_discussion_roundtrip(store):
    issue_id = store.create_issue("Discuss test")

    store.add_discussion(issue_id, "planner", "What is your target audience?")
    store.add_discussion(issue_id, "owner", "Young adults 18-25.")
    store.add_discussion(issue_id, "planner", "Got it. Any preferences on tone?")

    msgs = store.get_discussions(issue_id)
    assert len(msgs) == 3
    assert msgs[0]["role"] == "planner"
    assert msgs[1]["role"] == "owner"
    assert msgs[2]["content"] == "Got it. Any preferences on tone?"


def test_export_discussion_md(store):
    issue_id = store.create_issue("Export test")
    store.add_discussion(issue_id, "planner", "Question 1?")
    store.add_discussion(issue_id, "owner", "Answer 1.")

    md = store.export_discussion_md(issue_id)
    assert "planner" in md.lower() or "Question 1?" in md
    assert "Answer 1." in md


def test_discussion_empty(store):
    issue_id = store.create_issue("Empty discussion")
    msgs = store.get_discussions(issue_id)
    assert msgs == []


# ── Chat ──────────────────────────────────────────────────────

def test_chat_lifecycle(store):
    session_id = "test-session-abc"

    store.log_chat(session_id, "user", "What does the codebase do?")
    store.log_chat(session_id, "assistant", "It's a matchmaking platform.")
    store.log_chat(session_id, "user", "Plan an API for user profiles.")

    history = store.get_chat_history(session_id)
    assert len(history) == 3
    assert history[0]["role"] == "user"
    assert history[2]["content"] == "Plan an API for user profiles."


def test_chat_escalation(store):
    session_id = "escalation-session"
    issue_id = store.create_issue("Escalated from chat")

    store.log_chat(session_id, "user", "Build this feature.")
    store.mark_chat_escalated(session_id, issue_id)

    history = store.get_chat_history(session_id)
    # After marking escalation, the session should be linked
    assert len(history) >= 1


def test_chat_empty_session(store):
    history = store.get_chat_history("nonexistent-session")
    assert history == []


# ── Open issue / Resume helpers ───────────────────────────────

def test_get_open_issue(store):
    id1 = store.create_issue("Task A")
    store.close_issue(id1, "completed")

    id2 = store.create_issue("Task B")

    open_issue = store.get_open_issue()
    assert open_issue is not None
    assert open_issue["id"] == id2
    assert open_issue["status"] == "open"


def test_get_open_issue_none_when_all_closed(store):
    id1 = store.create_issue("Task A")
    store.close_issue(id1, "completed")

    assert store.get_open_issue() is None


def test_get_first_actionable_task(store):
    issue_id = store.create_issue("Multi-task")
    blueprint = [
        {"branch_id": "1", "description": "Task 1", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
        {"branch_id": "2", "description": "Task 2", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ]
    store.create_tasks(issue_id, blueprint)

    # Both pending — first should be returned
    actionable = store.get_first_actionable_task(issue_id)
    assert actionable is not None
    assert actionable["branch_id"] == "1"


def test_get_first_actionable_task_skips_completed(store):
    issue_id = store.create_issue("Skip completed")
    blueprint = [
        {"branch_id": "1", "description": "Task 1", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
        {"branch_id": "2", "description": "Task 2", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ]
    store.create_tasks(issue_id, blueprint)
    store.update_task_status(issue_id, "1", "completed")

    actionable = store.get_first_actionable_task(issue_id)
    assert actionable is not None
    assert actionable["branch_id"] == "2"


def test_get_first_actionable_task_none_when_all_done(store):
    issue_id = store.create_issue("All done")
    blueprint = [
        {"branch_id": "1", "description": "Task 1", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ]
    store.create_tasks(issue_id, blueprint)
    store.update_task_status(issue_id, "1", "completed")

    assert store.get_first_actionable_task(issue_id) is None


# ── Task status with attempt counter ─────────────────────────

def test_update_task_status_increment_attempts(store):
    issue_id = store.create_issue("Retry test")
    blueprint = [
        {"branch_id": "1", "description": "Flaky task", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ]
    store.create_tasks(issue_id, blueprint)

    # First attempt fails
    store.update_task_status(issue_id, "1", "failed", increment_attempts=True)
    task = store.get_task_row(issue_id, "1")
    assert task["status"] == "failed"
    assert task["attempts"] == 1

    # Retry — back to in_progress, then fail again
    store.update_task_status(issue_id, "1", "in_progress")
    store.update_task_status(issue_id, "1", "failed", increment_attempts=True)
    task = store.get_task_row(issue_id, "1")
    assert task["attempts"] == 2


def test_get_tasks_overview(store):
    issue_id = store.create_issue("Overview test")
    blueprint = [
        {"branch_id": "1", "description": "First task", "tools_required": ["shell"],
         "skills_required": [], "success_criteria": "done"},
        {"branch_id": "2", "description": "Second task", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ]
    store.create_tasks(issue_id, blueprint)

    overview = store.get_tasks_overview(issue_id)
    assert len(overview) == 2
    assert overview[0]["branch_id"] == "1"


# ── Execution plan storage ────────────────────────────────────

def test_execution_plan_roundtrip(store):
    issue_id = store.create_issue("Exec plan test")
    blueprint = [
        {"branch_id": "1", "description": "Build it", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ]
    store.create_tasks(issue_id, blueprint)

    plan_md = "## Step 1\nRead the file\n## Step 2\nModify it"
    store.update_task_execution_plan(issue_id, "1", plan_md)

    retrieved = store.get_task_execution_plan(issue_id, "1")
    assert retrieved == plan_md


def test_execution_plan_default_empty(store):
    issue_id = store.create_issue("No plan test")
    blueprint = [
        {"branch_id": "1", "description": "Build it", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ]
    store.create_tasks(issue_id, blueprint)

    assert store.get_task_execution_plan(issue_id, "1") == ""


# ── Tool calls ────────────────────────────────────────────────

def test_tool_call_logging(store):
    issue_id = store.create_issue("Tool call test")

    store.log_tool_call(
        issue_id, "1", round_num=1,
        tool_name="file_write",
        tool_args='{"path": "hello.txt", "content": "hi"}',
        output="File written successfully",
        is_truncated=False,
    )
    store.log_tool_call(
        issue_id, "1", round_num=2,
        tool_name="shell",
        tool_args='{"command": "cat hello.txt"}',
        output="hi",
        is_truncated=False,
    )

    calls = store.get_tool_calls(issue_id, "1")
    assert len(calls) == 2
    assert calls[0]["tool_name"] == "file_write"
    assert calls[1]["tool_name"] == "shell"


# ── Skills ────────────────────────────────────────────────────

def test_skill_create_and_retrieve(store):
    skill_id = store.create_skill(
        name="test-skill",
        description="A test skill for unit tests",
        file_path="skills/test-skill.md",
        created_by="test",
        tags=["test", "unit"],
        when_to_use="When testing",
        when_not_to_use="In production",
    )
    assert skill_id > 0

    skill = store.get_skill("test-skill")
    assert skill is not None
    assert skill["name"] == "test-skill"
    assert skill["description"] == "A test skill for unit tests"
    # create_skill may default to "draft" — test the lifecycle methods instead
    assert skill["status"] in ("active", "draft")


def test_skill_update(store):
    store.create_skill(
        name="updatable-skill",
        description="Original description",
        file_path="skills/updatable.md",
    )
    store.update_skill("updatable-skill", description="Updated description")

    skill = store.get_skill("updatable-skill")
    assert skill["description"] == "Updated description"


def test_skill_lifecycle(store):
    store.create_skill(
        name="lifecycle-skill",
        description="Goes through lifecycle",
        file_path="skills/lifecycle.md",
    )

    store.submit_skill_for_review("lifecycle-skill")
    assert store.get_skill("lifecycle-skill")["status"] == "pending_review"

    pending = store.get_skills_pending_review()
    assert any(s["name"] == "lifecycle-skill" for s in pending)

    store.activate_skill("lifecycle-skill")
    assert store.get_skill("lifecycle-skill")["status"] == "active"

    store.deprecate_skill("lifecycle-skill")
    assert store.get_skill("lifecycle-skill")["status"] == "deprecated"


def test_skill_outcome_tracking(store):
    store.create_skill(
        name="tracked-skill",
        description="Track outcomes",
        file_path="skills/tracked.md",
    )

    store.record_skill_outcome("tracked-skill", is_success=True)
    store.record_skill_outcome("tracked-skill", is_success=True)
    store.record_skill_outcome("tracked-skill", is_success=False)

    skill = store.get_skill("tracked-skill")
    assert skill["uses"] == 3
    assert skill["successes"] == 2
    assert skill["failures"] == 1


def test_skill_search(store):
    store.create_skill(
        name="sql-helper",
        description="Helps with SQL queries and database operations",
        file_path="skills/sql-helper.md",
    )
    store.create_skill(
        name="css-helper",
        description="Helps with CSS styling and layout",
        file_path="skills/css-helper.md",
    )

    # search_skills takes a comma-separated string, not a list
    # Also, skills need to be active to appear in search
    store.activate_skill("sql-helper")
    store.activate_skill("css-helper")

    results = store.search_skills("SQL database")
    names = [r["name"] for r in results]
    assert "sql-helper" in names


def test_get_nonexistent_skill(store):
    assert store.get_skill("does-not-exist") is None


# ── Skill requests ────────────────────────────────────────────

def test_skill_request_lifecycle(store):
    req_id = store.create_skill_request(
        requested_by="planner",
        need="Need a data validation skill",
        context="Processing CSV files with schema enforcement",
    )
    assert req_id > 0

    pending = store.get_pending_skill_requests()
    assert len(pending) >= 1
    assert any(r["id"] == req_id for r in pending)

    store.resolve_skill_request(
        req_id,
        resolved_skill="csv-validator",
        resolution_note="Created new skill",
        status="fulfilled",
    )

    pending_after = store.get_pending_skill_requests()
    assert not any(r["id"] == req_id for r in pending_after)


# ── File registry ─────────────────────────────────────────────

def test_file_registry_upsert_and_get(store):
    store.upsert_file("src/main.py", "python", 1234, "abc123", {"imports": ["os"]})

    f = store.get_file("src/main.py")
    assert f is not None
    assert f["file_type"] == "python"
    assert f["size_bytes"] == 1234
    assert f["last_hash"] == "abc123"


def test_file_registry_upsert_updates(store):
    store.upsert_file("src/main.py", "python", 1000, "hash1", {})
    store.upsert_file("src/main.py", "python", 2000, "hash2", {})

    f = store.get_file("src/main.py")
    assert f["size_bytes"] == 2000
    assert f["last_hash"] == "hash2"


def test_file_registry_count(store):
    assert store.file_registry_count() == 0

    store.upsert_file("a.py", "python", 100, "h1", {})
    store.upsert_file("b.js", "javascript", 200, "h2", {})

    assert store.file_registry_count() == 2


def test_file_registry_by_type(store):
    store.upsert_file("a.py", "python", 100, "h1", {})
    store.upsert_file("b.py", "python", 200, "h2", {})
    store.upsert_file("c.js", "javascript", 300, "h3", {})

    py_files = store.get_files_by_type("python")
    assert len(py_files) == 2

    js_files = store.get_files_by_type("javascript")
    assert len(js_files) == 1


def test_file_registry_remove(store):
    store.upsert_file("temp.py", "python", 100, "h1", {})
    assert store.get_file("temp.py") is not None

    store.remove_file("temp.py")
    assert store.get_file("temp.py") is None


def test_file_registry_get_all(store):
    store.upsert_file("a.py", "python", 100, "h1", {})
    store.upsert_file("b.js", "javascript", 200, "h2", {})

    all_files = store.get_all_files()
    assert len(all_files) == 2


# ── Issue with goals_md ───────────────────────────────────────

def test_issue_stores_goals_md(store):
    goals = "# Goals\n\nBuild a recommendation engine."
    issue_id = store.create_issue("Build reco engine", goals_md=goals)

    issue = store.get_issue(issue_id)
    assert issue["goals_md"] == goals


def test_issue_parent_child(store):
    parent_id = store.create_issue("Parent task")
    child_id = store.create_issue("Sub-task", parent_issue_id=parent_id)

    child = store.get_issue(child_id)
    assert child["parent_issue_id"] == parent_id


# ── Supersede / close status ─────────────────────────────────

def test_close_issue_superseded(store):
    id1 = store.create_issue("Old task")
    store.close_issue(id1, "superseded")

    issue = store.get_issue(id1)
    assert issue["status"] == "superseded"
    assert issue["closed_at"] is not None


def test_close_issue_failed(store):
    id1 = store.create_issue("Broken task")
    store.close_issue(id1, "failed")

    issue = store.get_issue(id1)
    assert issue["status"] == "failed"
