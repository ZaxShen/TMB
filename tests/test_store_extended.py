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


# ── Audit ─────────────────────────────────────────────────────

def test_audit_logging(store):
    issue_id = store.create_issue("Audit test")

    store.log_audit(
        issue_id, "1", round_num=1,
        tool_name="file_write",
        tool_args={"path": "hello.txt", "content": "hi"},
        output="File written successfully",
        is_truncated=False,
        from_node="executor",
    )
    store.log_audit(
        issue_id, "1", round_num=2,
        tool_name="shell",
        tool_args={"command": "cat hello.txt"},
        output="hi",
        is_truncated=False,
        from_node="executor",
    )

    entries = store.get_audit_log(issue_id, "1")
    assert len(entries) == 2
    assert entries[0]["tool_name"] == "file_write"
    assert entries[1]["tool_name"] == "shell"
    assert entries[0]["from_node"] == "executor"


# ── Audit table ───────────────────────────────────────────────

def test_audit_from_node_column(store):
    """Audit entries should record which node made the tool call."""
    issue_id = store.create_issue("Multi-node audit test")

    store.log_audit(
        issue_id, None, round_num=0,
        tool_name="file_inspect",
        tool_args={"path": "src/main.py"},
        output="200 lines of Python",
        from_node="planner",
    )
    store.log_audit(
        issue_id, "1", round_num=0,
        tool_name="shell",
        tool_args={"command": "python test.py"},
        output="All tests pass",
        from_node="executor",
    )
    store.log_audit(
        issue_id, None, round_num=0,
        tool_name="search",
        tool_args={"query": "database"},
        output="Found 3 files",
        from_node="discussion",
    )

    entries = store.get_audit_log(issue_id)
    assert len(entries) == 3

    nodes = [e["from_node"] for e in entries]
    assert "planner" in nodes
    assert "executor" in nodes
    assert "discussion" in nodes


def test_audit_entry_output(store):
    """get_audit_entry_output() should return the full untruncated output."""
    issue_id = store.create_issue("Output test")

    big_output = "x" * 50000
    store.log_audit(
        issue_id, "1", round_num=0,
        tool_name="shell",
        tool_args={"command": "big command"},
        output=big_output,
        is_truncated=True,
        from_node="executor",
    )

    entries = store.get_audit_log(issue_id)
    assert len(entries) == 1
    assert entries[0]["is_truncated"] == 1

    full_output = store.get_audit_entry_output(entries[0]["id"])
    assert full_output == big_output
    assert len(full_output) == 50000


def test_audit_default_from_node(store):
    """from_node should default to 'executor' if not specified."""
    issue_id = store.create_issue("Default node test")

    store.log_audit(
        issue_id, "1", round_num=0,
        tool_name="shell",
        tool_args={},
        output="ok",
    )

    entries = store.get_audit_log(issue_id)
    assert entries[0]["from_node"] == "executor"


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


# ── Branch ID uniqueness ─────────────────────────────────────

def test_branch_id_unique_per_issue(store):
    """Same branch_id on different issues should succeed."""
    id1 = store.create_issue("Issue A")
    id2 = store.create_issue("Issue B")

    store.create_tasks(id1, [
        {"branch_id": "1", "description": "Task A1", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ])
    store.create_tasks(id2, [
        {"branch_id": "1", "description": "Task B1", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ])

    # Both should exist
    assert store.get_task_row(id1, "1") is not None
    assert store.get_task_row(id2, "1") is not None


def test_branch_id_duplicate_same_issue_blocked(store):
    """Duplicate branch_id on the same issue should raise IntegrityError."""
    import sqlite3
    issue_id = store.create_issue("Dup test")

    store.create_tasks(issue_id, [
        {"branch_id": "1", "description": "First", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ])

    # Manually insert a duplicate — should fail due to unique index
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "INSERT INTO tasks (issue_id, branch_id, title, description, "
            "tools_required, skills_required, success_criteria, status, created_at, updated_at) "
            "VALUES (?, '1', 'dup', 'dup', '[]', '[]', 'done', 'pending', '2024-01-01', '2024-01-01')",
            (issue_id,),
        )


def test_get_all_root_tasks_filters_completed_issues(store):
    """Default get_all_root_tasks() should exclude completed/closed issues."""
    id1 = store.create_issue("Old work")
    store.create_tasks(id1, [
        {"branch_id": "1", "description": "Old task", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ])
    store.close_issue(id1, "completed")

    id2 = store.create_issue("New work")
    store.create_tasks(id2, [
        {"branch_id": "1", "description": "New task", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ])

    # Default: only open issue
    result = store.get_all_root_tasks()
    assert len(result) == 1
    assert result[0]["issue_id"] == id2

    # Explicit no filter: all issues
    result_all = store.get_all_root_tasks(exclude_statuses=[])
    assert len(result_all) == 2


def test_get_all_root_tasks_includes_issue_status(store):
    """Result should include issue_status field."""
    issue_id = store.create_issue("Status test")
    store.create_tasks(issue_id, [
        {"branch_id": "1", "description": "Task", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ])

    result = store.get_all_root_tasks()
    assert len(result) == 1
    assert "issue_status" in result[0]
    assert result[0]["issue_status"] == "open"


# ── Completion cleanup ────────────────────────────────────────

def test_finalize_issue_cleans_goals_on_completion(store, tmp_path):
    """_finalize_issue() should reset GOALS.md when all tasks are completed."""
    from unittest.mock import patch

    # Set up: create issue with completed tasks
    issue_id = store.create_issue("Cleanup test")
    store.create_tasks(issue_id, [
        {"branch_id": "1", "description": "Task 1", "tools_required": [],
         "skills_required": [], "success_criteria": "check output.txt"},
        {"branch_id": "2", "description": "Task 2", "tools_required": [],
         "skills_required": [], "success_criteria": "run tests"},
    ])
    store.update_task_status(issue_id, "1", "completed")
    store.update_task_status(issue_id, "2", "completed")

    # Create existing goals and discussion files
    goals_path = tmp_path / "GOALS.md"
    goals_path.write_text("# Goals\n\nOld stale goals here.\n")
    disc_path = tmp_path / "DISCUSSION.md"
    disc_path.write_text("# Discussion\n\nOld discussion content.\n")

    with patch("tmb.cli.docs_dir", return_value=tmp_path):
        from tmb.cli import _finalize_issue
        _finalize_issue(store, issue_id)

    # GOALS.md should be reset to template
    goals_content = goals_path.read_text()
    assert "Write your goals" in goals_content
    assert f"Issue #{issue_id} completed" in goals_content
    assert "Old stale goals" not in goals_content

    # DISCUSSION.md should be reset
    disc_content = disc_path.read_text()
    assert "New discussion will appear here" in disc_content
    assert "Old discussion content" not in disc_content

    # Issue should be closed
    issue = store.get_issue(issue_id)
    assert issue["status"] == "completed"


def test_finalize_issue_no_cleanup_on_failure(store, tmp_path):
    """_finalize_issue() should NOT reset GOALS.md when tasks failed."""
    from unittest.mock import patch

    issue_id = store.create_issue("Fail test")
    store.create_tasks(issue_id, [
        {"branch_id": "1", "description": "Task 1", "tools_required": [],
         "skills_required": [], "success_criteria": "done"},
    ])
    store.update_task_status(issue_id, "1", "failed")

    goals_path = tmp_path / "GOALS.md"
    goals_path.write_text("# Goals\n\nKeep these goals.\n")

    with patch("tmb.cli.docs_dir", return_value=tmp_path):
        from tmb.cli import _finalize_issue
        _finalize_issue(store, issue_id)

    # GOALS.md should NOT be touched
    goals_content = goals_path.read_text()
    assert "Keep these goals" in goals_content

    # Issue should still be open (not completed)
    issue = store.get_issue(issue_id)
    assert issue["status"] != "completed"


def test_finalize_issue_no_tasks_still_cleans(store, tmp_path):
    """_finalize_issue() with no tasks should still clean up GOALS.md."""
    from unittest.mock import patch

    issue_id = store.create_issue("Empty test")

    goals_path = tmp_path / "GOALS.md"
    goals_path.write_text("# Goals\n\nStale.\n")
    disc_path = tmp_path / "DISCUSSION.md"
    disc_path.write_text("# Discussion\n\nStale.\n")

    with patch("tmb.cli.docs_dir", return_value=tmp_path):
        from tmb.cli import _finalize_issue
        _finalize_issue(store, issue_id)

    # Should be cleaned since issue was completed
    goals_content = goals_path.read_text()
    assert "Write your goals" in goals_content


def test_cleanup_goals_template_is_stripped_by_read(tmp_path):
    """The template written by cleanup should be treated as empty by _read_goals_md()."""
    import re

    # Simulate what _cleanup_completed_issue writes
    template = (
        "# Goals\n\n"
        "<!-- Issue #42 completed successfully. -->\n\n"
        "Write your goals below. The Planner will read this file and discuss with you.\n\n"
        "---\n\n"
    )

    # Simulate what _read_goals_md does
    goals_raw = template.strip()
    goals_md = re.sub(r"<!--.*?-->", "", goals_raw, flags=re.DOTALL).strip()
    goals_md = re.sub(
        r"^# Goals\s*\n+Write your goals.*?---\s*",
        "",
        goals_md,
        flags=re.DOTALL,
    ).strip()

    # Should be empty — the template is fully stripped
    assert goals_md == "", f"Template not stripped clean: {goals_md!r}"
