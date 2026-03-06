# Skill: Branch Operations

> Patterns for working with hierarchical branch IDs across tasks and issues.

---

## Branch ID Convention

Tasks use hierarchical string IDs that encode semantic relationships:

```
1           — top-level feature (e.g., "user authentication")
1.1         — sub-feature (e.g., "email login")
1.1.1       — implementation detail (e.g., "email validation")
1.2         — sibling sub-feature (e.g., "OAuth login")
2           — independent top-level feature
```

## Querying by Branch

```python
store = Store()

# All tasks under a branch prefix (any issue)
tree = store.get_task_tree("1")         # returns 1, 1.1, 1.1.1, 1.2, ...
subtree = store.get_task_tree("1.1")    # returns 1.1, 1.1.1, ...

# All root-level tasks across the project
roots = store.get_all_root_tasks()      # parent_branch_id IS NULL
```

## Deleting a Branch

```python
# Removes tasks AND their ledger entries matching the prefix
store.delete_task_branch("1.1")  # deletes 1.1, 1.1.1, 1.1.2, ...
```

## Deriving Parent

The parent is derived by stripping the last segment:

```python
bid = "1.2.3"
parent = ".".join(bid.split(".")[:-1])  # "1.2"
# Root tasks (e.g., "1") have parent_branch_id = None
```

## Cross-Issue Linking

Issues can reference parent issues:

```python
store.create_issue("child objective", goals_md, parent_issue_id=5)
```

## Rules

1. **Planner assigns branch IDs.** The Planner generates branch IDs based on the existing task tree to maintain semantic structure across the project's lifetime.
2. **Branch operations use SQL LIKE.** `branch_id LIKE '1.%'` is the canonical pattern — no full table scans needed.
3. **Never reuse a branch ID** that was previously deleted — it breaks audit trail references in the ledger.
4. **`get_all_root_tasks()`** is the Planner's entry point for understanding the project-wide task landscape before assigning new IDs.
