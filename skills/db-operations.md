# Skill: DB Operations

> Efficient patterns for querying and mutating `baymax_history.db` via the `Store` API.

---

## Lightweight Queries (prefer these)

Use overview methods that return metadata only — no large JSON/text blobs:

```python
store = Store()

# Task metadata: id, branch_id, title, status, attempts — no description
tasks = store.get_tasks_overview(issue_id)

# Ledger entries: id, event_type, summary, timestamp — no JSON content
entries = store.get_ledger_overview(issue_id)

# Full skill index: name, description, tags — no file content
skills = store.get_all_skills()
```

## Full Reads (only when detail is needed)

```python
# Full task row — includes description, execution_plan_md, qa_results
task = store.get_task_row(issue_id, branch_id)

# Full ledger with JSON content
entries = store.get_ledger(issue_id)

# All tasks with full descriptions
tasks = store.get_tasks(issue_id)
```

## Creating & Updating

```python
# Create tasks from blueprint — replaces any existing tasks for the issue
store.create_tasks(issue_id, blueprint)

# Update status
store.update_task_status(issue_id, branch_id, "completed")

# Log to ledger (always include summary for lightweight queries)
store.log(issue_id, branch_id, "executor", "task_started", {
    "detail": "..."
}, summary="Started implementation of auth module")
```

## Rules

1. **Always use overview methods first.** Only fetch full content when you need the description or JSON details for the current operation.
2. **Always include `summary`** in `store.log()` calls — this powers the lightweight ledger.
3. **Never read the entire ledger content** to determine workflow state. Use `has_event()` or `get_first_actionable_task()` instead.
4. **Task title** is auto-extracted from the first line of the description — keep the first line meaningful.
