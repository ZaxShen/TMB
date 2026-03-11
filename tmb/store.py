"""SQLite audit store — full workflow history.

Tables:
  issues          — Project Owner objectives
  discussions     — Planner–Owner Q&A exchanges (permanent; doc file is overwritten)
  tasks           — Blueprint items assigned to Executor
  ledger          — Append-only log of every agent action
  skills          — Curated + agent-created skill metadata
  skill_requests  — Unfulfilled skill requests
  token_usage     — Per-invocation token counts
  tool_calls      — Full tool invocation log (args + untruncated output)
  file_registry   — Persistent map of discovered project files (zero-rescan upgrades)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def _split_task_description(desc: str) -> tuple[str, str]:
    """Split a task description into a short title and the full body."""
    first_line = desc.split("\n")[0].strip()
    title = first_line[:120]
    body = desc[len(first_line):].strip() if len(desc) > len(first_line) else ""
    return title, body


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            from tmb.paths import db_path as _default_db_path
            db_path = _default_db_path()
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS issues (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_issue_id   INTEGER REFERENCES issues(id),
                objective         TEXT    NOT NULL,
                goals_md          TEXT    NOT NULL DEFAULT '',
                status            TEXT    NOT NULL DEFAULT 'open',
                current_task_id   INTEGER REFERENCES tasks(id),
                created_at        TEXT    NOT NULL,
                updated_at        TEXT    NOT NULL,
                closed_at         TEXT
            );

            CREATE TABLE IF NOT EXISTS discussions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id    INTEGER NOT NULL REFERENCES issues(id),
                role        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id            INTEGER NOT NULL REFERENCES issues(id),
                branch_id           TEXT    NOT NULL,
                parent_branch_id    TEXT,
                title               TEXT    NOT NULL DEFAULT '',
                description         TEXT    NOT NULL,
                tools_required      TEXT    NOT NULL DEFAULT '[]',
                skills_required     TEXT    NOT NULL DEFAULT '[]',
                success_criteria    TEXT    NOT NULL,
                status              TEXT    NOT NULL DEFAULT 'pending',
                attempts            INTEGER NOT NULL DEFAULT 0,
                execution_plan_md   TEXT    NOT NULL DEFAULT '',
                qa_results          TEXT    NOT NULL DEFAULT '',
                created_at          TEXT    NOT NULL,
                updated_at          TEXT    NOT NULL,
                completed_at        TEXT
            );

            CREATE TABLE IF NOT EXISTS ledger (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id    INTEGER NOT NULL REFERENCES issues(id),
                branch_id   TEXT,
                from_node   TEXT    NOT NULL,
                event_type  TEXT    NOT NULL,
                summary     TEXT    NOT NULL DEFAULT '',
                content     TEXT    NOT NULL DEFAULT '{}',
                created_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skills (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT    NOT NULL UNIQUE,
                description     TEXT    NOT NULL,
                file_path       TEXT    NOT NULL,
                tags            TEXT    NOT NULL DEFAULT '[]',
                created_by      TEXT    NOT NULL DEFAULT 'system',
                trust_tier      TEXT    NOT NULL DEFAULT 'curated',
                status          TEXT    NOT NULL DEFAULT 'active',
                when_to_use     TEXT    NOT NULL DEFAULT '',
                when_not_to_use TEXT    NOT NULL DEFAULT '',
                uses            INTEGER NOT NULL DEFAULT 0,
                successes       INTEGER NOT NULL DEFAULT 0,
                failures        INTEGER NOT NULL DEFAULT 0,
                effectiveness   REAL,
                created_at      TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS skill_requests (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                requested_by    TEXT    NOT NULL,
                need            TEXT    NOT NULL,
                context         TEXT    NOT NULL DEFAULT '',
                status          TEXT    NOT NULL DEFAULT 'pending',
                resolved_skill  TEXT,
                resolution_note TEXT    NOT NULL DEFAULT '',
                created_at      TEXT    NOT NULL,
                resolved_at     TEXT
            );

            CREATE TABLE IF NOT EXISTS token_usage (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id        INTEGER NOT NULL REFERENCES issues(id),
                node            TEXT    NOT NULL,
                input_tokens    INTEGER NOT NULL DEFAULT 0,
                output_tokens   INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id        INTEGER NOT NULL REFERENCES issues(id),
                branch_id       TEXT,
                round           INTEGER NOT NULL DEFAULT 0,
                tool_name       TEXT    NOT NULL,
                tool_args       TEXT    NOT NULL DEFAULT '{}',
                output          TEXT    NOT NULL DEFAULT '',
                output_chars    INTEGER NOT NULL DEFAULT 0,
                is_truncated    INTEGER NOT NULL DEFAULT 0,
                created_at      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS file_registry (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                rel_path        TEXT    NOT NULL UNIQUE,
                file_type       TEXT    NOT NULL DEFAULT 'unknown',
                size_bytes      INTEGER NOT NULL DEFAULT 0,
                last_hash       TEXT    NOT NULL DEFAULT '',
                discovered_at   TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL,
                meta            TEXT    NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id      TEXT    NOT NULL,
                role            TEXT    NOT NULL,
                content         TEXT    NOT NULL,
                escalated_to    INTEGER REFERENCES issues(id),
                created_at      TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS project_context (
                key             TEXT    PRIMARY KEY,
                value           TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL
            );
        """)
        self._migrate()

    def _migrate(self):
        """Add columns that may be missing from older databases."""
        task_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
        for col, default in [
            ("title", "''"),
            ("branch_id", "''"),
            ("parent_branch_id", "NULL"),
            ("skills_required", "'[]'"),
            ("execution_plan_md", "''"),
            ("qa_results", "''"),
        ]:
            if col not in task_cols:
                if default == "NULL":
                    self._conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} TEXT")
                else:
                    self._conn.execute(
                        f"ALTER TABLE tasks ADD COLUMN {col} TEXT NOT NULL DEFAULT {default}"
                    )

        issue_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(issues)").fetchall()
        }
        if "parent_issue_id" not in issue_cols:
            self._conn.execute("ALTER TABLE issues ADD COLUMN parent_issue_id INTEGER")

        ledger_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(ledger)").fetchall()
        }
        if "summary" not in ledger_cols:
            self._conn.execute(
                "ALTER TABLE ledger ADD COLUMN summary TEXT NOT NULL DEFAULT ''"
            )

        skill_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(skills)").fetchall()
        } if self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='skills'"
        ).fetchone() else set()

        for col, spec in [
            ("trust_tier", "TEXT NOT NULL DEFAULT 'curated'"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("when_to_use", "TEXT NOT NULL DEFAULT ''"),
            ("when_not_to_use", "TEXT NOT NULL DEFAULT ''"),
            ("uses", "INTEGER NOT NULL DEFAULT 0"),
            ("successes", "INTEGER NOT NULL DEFAULT 0"),
            ("failures", "INTEGER NOT NULL DEFAULT 0"),
            ("effectiveness", "REAL"),
        ]:
            if col not in skill_cols:
                self._conn.execute(f"ALTER TABLE skills ADD COLUMN {col} {spec}")

        self._conn.commit()
        self._seed_skills()

    _SEED_APPLICABILITY = {
        "db-operations": {
            "when_to_use": "Tasks involving SQLite queries, Store API calls, or ledger logging",
            "when_not_to_use": "Tasks that only read/write project source files with no DB interaction",
        },
        "branch-operations": {
            "when_to_use": "Tasks involving hierarchical task IDs, tree queries, or branch-level operations",
            "when_not_to_use": "Simple single-task execution with no cross-task references",
        },
        "file-access": {
            "when_to_use": "Tasks that read or write files across permission boundaries",
            "when_not_to_use": "Tasks confined to a single source file with no doc/ or config/ interaction",
        },
        "mcp-patterns": {
            "when_to_use": "Tasks involving MCP server connections, tool generation, or external service integration",
            "when_not_to_use": "Tasks with no external service dependencies or MCP interaction",
        },
    }

    def _seed_skills(self):
        """Register built-in skill files from TMB/skills/ if not already in DB."""
        from tmb.paths import SEED_SKILLS_DIR, TMB_ROOT
        if not SEED_SKILLS_DIR.is_dir():
            return
        existing = {r["name"] for r in self.get_all_skills(include_inactive=True)}
        for md in sorted(SEED_SKILLS_DIR.glob("*.md")):
            name = md.stem
            if name in existing:
                continue
            lines = md.read_text().splitlines()
            desc = ""
            for line in lines:
                if line.startswith(">"):
                    desc = line.lstrip("> ").strip()
                    break
            applicability = self._SEED_APPLICABILITY.get(name, {})
            self.create_skill(
                name=name,
                description=desc or name,
                file_path=str(md.relative_to(TMB_ROOT)),
                created_by="system",
                tags=["built-in"],
                when_to_use=applicability.get("when_to_use", ""),
                when_not_to_use=applicability.get("when_not_to_use", ""),
            )

    # ── Issues ──────────────────────────────────────────────

    def create_issue(self, objective: str, goals_md: str = "", parent_issue_id: int | None = None) -> int:
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO issues (objective, goals_md, parent_issue_id, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'open', ?, ?)",
            (objective, goals_md, parent_issue_id, now, now),
        )
        self._conn.commit()
        issue_id = cur.lastrowid
        self.log(issue_id, None, "owner", "issue_opened", {"objective": objective},
                 summary=f"Issue opened: {objective[:100]}")
        return issue_id

    def update_issue_current_task(self, issue_id: int, task_row_id: int):
        self._conn.execute(
            "UPDATE issues SET current_task_id = ?, updated_at = ? WHERE id = ?",
            (task_row_id, _now(), issue_id),
        )
        self._conn.commit()

    def close_issue(self, issue_id: int, status: str = "closed"):
        self._conn.execute(
            "UPDATE issues SET status = ?, updated_at = ?, closed_at = ? WHERE id = ?",
            (status, _now(), _now(), issue_id),
        )
        self._conn.commit()
        self.log(issue_id, None, "system", "issue_closed", {"status": status},
                 summary=f"Issue closed: {status}")

    def get_issue(self, issue_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        return dict(row) if row else None

    def get_open_issue(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM issues WHERE status = 'open' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def claim_open_issue(self) -> dict | None:
        """Atomically find and claim the latest open issue (race-safe).

        Uses UPDATE … WHERE status='open' so only one process wins when
        multiple callers race on the same issue.
        """
        row = self._conn.execute(
            "SELECT id FROM issues WHERE status = 'open' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        issue_id = row["id"]
        self._conn.execute(
            "UPDATE issues SET status = 'in_progress', updated_at = ? "
            "WHERE id = ? AND status = 'open'",
            (_now(), issue_id),
        )
        self._conn.commit()
        if self._conn.total_changes == 0:
            return None  # another process claimed it first
        return self.get_issue(issue_id)

    # ── Ledger queries ───────────────────────────────────────

    def has_event(self, issue_id: int, event_type: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM ledger WHERE issue_id = ? AND event_type = ? LIMIT 1",
            (issue_id, event_type),
        ).fetchone()
        return row is not None

    # ── Task queries ─────────────────────────────────────────

    def get_first_actionable_task(self, issue_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE issue_id = ? AND status IN ('pending', 'failed', 'in_progress', 'escalated') ORDER BY id LIMIT 1",
            (issue_id,),
        ).fetchone()
        return dict(row) if row else None

    # ── Discussions ─────────────────────────────────────────

    def add_discussion(self, issue_id: int, role: str, content: str):
        self._conn.execute(
            "INSERT INTO discussions (issue_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (issue_id, role, content, _now()),
        )
        self._conn.commit()

    def get_discussions(self, issue_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM discussions WHERE issue_id = ? ORDER BY id", (issue_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def export_discussion_md(self, issue_id: int) -> str:
        """Export current discussion as Markdown. This overwrites bro/DISCUSSION.md
        each time — previous discussions are preserved only in the DB."""
        issue = self.get_issue(issue_id)
        discussions = self.get_discussions(issue_id)
        lines = [
            f"# Discussion — Issue #{issue_id}",
            "",
            f"> This file reflects the **current** discussion only.",
            f"> Previous discussions are preserved in the database.",
            "",
            f"**Objective**: {issue['objective']}",
            f"**Date**: {issue['created_at']}",
            "",
            "---",
            "",
        ]
        for d in discussions:
            from tmb.config import get_role_name
            label = f"**{get_role_name('owner')}**" if d["role"] in ("cto", "owner") else f"**{get_role_name('planner')}**"
            lines.append(f"### {label}")
            lines.append(f"*{d['created_at']}*")
            lines.append("")
            lines.append(d["content"])
            lines.append("")
            lines.append("---")
            lines.append("")
        return "\n".join(lines)

    # ── Tasks ───────────────────────────────────────────────

    def create_tasks(self, issue_id: int, blueprint: list[dict]):
        now = _now()
        existing = self.get_tasks(issue_id)
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            if existing:
                self._conn.execute(
                    "DELETE FROM tasks WHERE issue_id = ?", (issue_id,)
                )

            for task in blueprint:
                bid = str(task["branch_id"])
                desc = task["description"]
                title = desc.split("\n")[0][:120].strip()
                parent = ".".join(bid.split(".")[:-1]) or None
                self._conn.execute(
                    "INSERT INTO tasks (issue_id, branch_id, parent_branch_id, title, description, "
                    "tools_required, skills_required, success_criteria, status, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
                    (
                        issue_id,
                        bid,
                        parent,
                        title,
                        desc,
                        json.dumps(task.get("tools_required", [])),
                        json.dumps(task.get("skills_required", [])),
                        task["success_criteria"],
                        now,
                        now,
                    ),
                )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise

        if existing:
            self.log(issue_id, None, "planner", "blueprint_superseded", {
                "old_task_count": len(existing),
            }, summary=f"Replaced {len(existing)} old tasks")
        self.log(issue_id, None, "planner", "blueprint_created", {
            "task_count": len(blueprint),
        }, summary=f"Blueprint: {len(blueprint)} tasks")

    def update_task_status(self, issue_id: int, branch_id: str, status: str, increment_attempts: bool = False):
        now = _now()
        if increment_attempts:
            self._conn.execute(
                "UPDATE tasks SET status = ?, attempts = attempts + 1, updated_at = ? WHERE issue_id = ? AND branch_id = ?",
                (status, now, issue_id, branch_id),
            )
        else:
            updates = "status = ?, updated_at = ?"
            params: list[Any] = [status, now]
            if status == "completed":
                updates += ", completed_at = ?"
                params.append(now)
            params.extend([issue_id, branch_id])
            self._conn.execute(
                f"UPDATE tasks SET {updates} WHERE issue_id = ? AND branch_id = ?",
                params,
            )
        self._conn.commit()

        row = self._conn.execute(
            "SELECT id FROM tasks WHERE issue_id = ? AND branch_id = ?", (issue_id, branch_id)
        ).fetchone()
        if row:
            self.update_issue_current_task(issue_id, row["id"])

    def get_tasks(self, issue_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE issue_id = ? ORDER BY id", (issue_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_tasks_overview(self, issue_id: int) -> list[dict]:
        """Lightweight task list — only metadata, no heavy text columns."""
        rows = self._conn.execute(
            "SELECT id, issue_id, branch_id, parent_branch_id, title, status, attempts, "
            "created_at, updated_at, completed_at "
            "FROM tasks WHERE issue_id = ? ORDER BY id",
            (issue_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_task_row(self, issue_id: int, branch_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE issue_id = ? AND branch_id = ?", (issue_id, branch_id)
        ).fetchone()
        return dict(row) if row else None

    # ── Task tree operations ──────────────────────────────────

    def get_task_tree(self, prefix: str) -> list[dict]:
        """Get all tasks (across all issues) whose branch_id starts with prefix.

        Example: get_task_tree("1") returns tasks "1", "1.1", "1.2", "1.1.1", etc.
        """
        rows = self._conn.execute(
            "SELECT id, issue_id, branch_id, parent_branch_id, title, status, attempts, "
            "created_at, updated_at, completed_at "
            "FROM tasks WHERE branch_id = ? OR branch_id LIKE ? ORDER BY id",
            (prefix, f"{prefix}.%"),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_root_tasks(self) -> list[dict]:
        """Project-wide overview of root-level tasks (no parent) — for Architect context."""
        rows = self._conn.execute(
            "SELECT t.branch_id, t.title, t.status, t.issue_id, i.objective "
            "FROM tasks t JOIN issues i ON t.issue_id = i.id "
            "WHERE t.parent_branch_id IS NULL "
            "ORDER BY t.id",
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_task_branch(self, prefix: str):
        """Delete all tasks whose branch_id starts with prefix (branch removal).

        Example: delete_task_branch("1") deletes "1", "1.1", "1.2", "1.1.1", etc.
        Also cleans up related ledger entries.
        """
        self._conn.execute(
            "DELETE FROM ledger WHERE branch_id = ? OR branch_id LIKE ?",
            (prefix, f"{prefix}.%"),
        )
        self._conn.execute(
            "DELETE FROM tasks WHERE branch_id = ? OR branch_id LIKE ?",
            (prefix, f"{prefix}.%"),
        )
        self._conn.commit()

    def update_task_execution_plan(self, issue_id: int, branch_id: str, plan_md: str):
        """Store the per-task execution plan generated by the Planner."""
        self._conn.execute(
            "UPDATE tasks SET execution_plan_md = ?, updated_at = ? WHERE issue_id = ? AND branch_id = ?",
            (plan_md, _now(), issue_id, branch_id),
        )
        self._conn.commit()

    def get_task_execution_plan(self, issue_id: int, branch_id: str) -> str:
        """Read the execution plan for a single task."""
        row = self._conn.execute(
            "SELECT execution_plan_md FROM tasks WHERE issue_id = ? AND branch_id = ?",
            (issue_id, branch_id),
        ).fetchone()
        return row["execution_plan_md"] if row else ""

    def archive_task_execution(self, issue_id: int, branch_id: str, execution_plan_md: str):
        """Archive the EXECUTION.md section for a completed task (legacy)."""
        self.update_task_execution_plan(issue_id, branch_id, execution_plan_md)

    def archive_task_qa_results(self, issue_id: int, branch_id: str, qa_results: str):
        """Archive QA results/evidence for a task."""
        self._conn.execute(
            "UPDATE tasks SET qa_results = ?, updated_at = ? WHERE issue_id = ? AND branch_id = ?",
            (qa_results, _now(), issue_id, branch_id),
        )
        self._conn.commit()

    def export_blueprint_md(self, issue_id: int, blueprint: list[dict] | None = None) -> str:
        """Generate blueprint markdown. If blueprint is None, reads tasks from DB with live statuses."""
        issue = self.get_issue(issue_id)
        now = _now()

        if blueprint is None:
            tasks = self.get_tasks(issue_id)
        else:
            tasks = None

        items = tasks if tasks is not None else blueprint
        status_icons = {
            "pending": " ", "in_progress": "~", "completed": "x",
            "failed": "!", "escalated": "^",
        }

        completed = sum(1 for t in items if t.get("status") == "completed") if tasks else 0
        total = len(items)
        progress = f" ({completed}/{total} completed)" if tasks else ""

        lines = [
            f"# Blueprint — Issue #{issue_id}",
            "",
            f"**Objective**: {issue['objective']}",
            f"**Updated**: {now}",
            f"**Tasks**: {total}{progress}",
            "",
            "---",
            "",
        ]
        for t in items:
            bid = t.get("branch_id", "?")
            desc = t.get("description", "")
            status = t.get("status", "")
            icon = status_icons.get(status, " ")
            status_label = f" [{status}]" if status else ""

            lines.append(f"## [{icon}] Task {bid}: {desc}")
            lines.append("")
            tools = t.get("tools_required", [])
            if isinstance(tools, str):
                import json as _json
                try:
                    tools = _json.loads(tools)
                except Exception:
                    tools = []
            lines.append(f"- **Tools**: {', '.join(tools)}")
            lines.append(f"- **Success criteria**: {t.get('success_criteria', '')}")
            if status:
                lines.append(f"- **Status**: {status}")
            lines.append("")
        return "\n".join(lines)

    # ── Ledger ──────────────────────────────────────────────

    def log(self, issue_id: int, branch_id: str | None, from_node: str, event_type: str, content: dict | str = "", summary: str = ""):
        if isinstance(content, dict):
            content = json.dumps(content)
        if not summary:
            summary = event_type.replace("_", " ")
        self._conn.execute(
            "INSERT INTO ledger (issue_id, branch_id, from_node, event_type, summary, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (issue_id, branch_id, from_node, event_type, summary[:200], content, _now()),
        )
        self._conn.commit()

    # ── Token usage ────────────────────────────────────────────

    def log_tokens(self, issue_id: int, node: str, input_tokens: int, output_tokens: int):
        """Record token usage from a single node invocation."""
        if input_tokens == 0 and output_tokens == 0:
            return
        self._conn.execute(
            "INSERT INTO token_usage (issue_id, node, input_tokens, output_tokens, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (issue_id, node, input_tokens, output_tokens, _now()),
        )
        self._conn.commit()

    # ── Tool calls ─────────────────────────────────────────────

    def log_tool_call(self, issue_id: int, branch_id: str | None, round_num: int,
                      tool_name: str, tool_args: dict, output: str,
                      is_truncated: bool = False):
        """Record a single tool invocation with its full (untruncated) output."""
        self._conn.execute(
            "INSERT INTO tool_calls (issue_id, branch_id, round, tool_name, tool_args, "
            "output, output_chars, is_truncated, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (issue_id, branch_id, round_num, tool_name, json.dumps(tool_args),
             output, len(output), int(is_truncated), _now()),
        )
        self._conn.commit()

    def get_tool_calls(self, issue_id: int, branch_id: str | None = None) -> list[dict]:
        """Retrieve tool call log for debugging. Omits full output by default."""
        if branch_id is not None:
            rows = self._conn.execute(
                "SELECT id, issue_id, branch_id, round, tool_name, tool_args, "
                "output_chars, is_truncated, created_at "
                "FROM tool_calls WHERE issue_id = ? AND branch_id = ? ORDER BY id",
                (issue_id, branch_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, issue_id, branch_id, round, tool_name, tool_args, "
                "output_chars, is_truncated, created_at "
                "FROM tool_calls WHERE issue_id = ? ORDER BY id",
                (issue_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_tool_call_output(self, tool_call_id: int) -> str | None:
        """Retrieve the full untruncated output of a specific tool call."""
        row = self._conn.execute(
            "SELECT output FROM tool_calls WHERE id = ?", (tool_call_id,)
        ).fetchone()
        return row["output"] if row else None

    def log_chat(self, session_id: str, role: str, content: str,
                 escalated_to: int | None = None):
        self._conn.execute(
            "INSERT INTO chat_messages (session_id, role, content, escalated_to, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, role, content, escalated_to, _now()),
        )
        self._conn.commit()

    def get_chat_history(self, session_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_chat_escalated(self, session_id: str, issue_id: int):
        self._conn.execute(
            "UPDATE chat_messages SET escalated_to = ? WHERE session_id = ? AND escalated_to IS NULL",
            (issue_id, session_id),
        )
        self._conn.commit()

    def get_token_summary(self, issue_id: int) -> dict:
        """Aggregate token usage by node for an issue.

        Returns {"planner": {"in": N, "out": N}, ..., "total": {"in": N, "out": N}}
        """
        rows = self._conn.execute(
            "SELECT node, SUM(input_tokens) as inp, SUM(output_tokens) as outp "
            "FROM token_usage WHERE issue_id = ? GROUP BY node ORDER BY node",
            (issue_id,),
        ).fetchall()
        result = {}
        total_in = total_out = 0
        for r in rows:
            result[r["node"]] = {"in": r["inp"], "out": r["outp"]}
            total_in += r["inp"]
            total_out += r["outp"]
        result["total"] = {"in": total_in, "out": total_out}
        return result

    # ── Ledger ────────────────────────────────────────────────

    def get_ledger(self, issue_id: int, branch_id: str | None = None) -> list[dict]:
        if branch_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM ledger WHERE issue_id = ? AND branch_id = ? ORDER BY id",
                (issue_id, branch_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM ledger WHERE issue_id = ? ORDER BY id", (issue_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_ledger_overview(self, issue_id: int) -> list[dict]:
        """Lightweight ledger — summaries only, no JSON content blobs."""
        rows = self._conn.execute(
            "SELECT id, issue_id, branch_id, from_node, event_type, summary, created_at "
            "FROM ledger WHERE issue_id = ? ORDER BY id",
            (issue_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Skills ──────────────────────────────────────────────
    #
    # Trust tiers:
    #   curated   — created by system or human; always trusted
    #   agent     — created by an agent during execution; starts as draft
    #
    # Status lifecycle:
    #   draft     → pending_review → active → deprecated
    #   Curated skills skip draft/pending_review and start as active.
    #
    # Effectiveness:
    #   Tracked per-skill via uses/successes/failures counters.
    #   effectiveness = successes / uses (NULL until first use).
    #   Auto-deprecated when uses >= 5 AND effectiveness < 0.3.

    _EFFECTIVENESS_MIN_USES = 5
    _EFFECTIVENESS_DEPRECATE_THRESHOLD = 0.3

    def create_skill(self, name: str, description: str, file_path: str,
                     created_by: str = "system", tags: list[str] | None = None,
                     when_to_use: str = "", when_not_to_use: str = "") -> int:
        is_curated = created_by in ("system", "human", "chief_architect", "owner", "planner")
        trust_tier = "curated" if is_curated else "agent"
        status = "active" if is_curated else "draft"
        now = _now()
        cur = self._conn.execute(
            "INSERT OR REPLACE INTO skills "
            "(name, description, file_path, tags, created_by, trust_tier, status, "
            " when_to_use, when_not_to_use, uses, successes, failures, effectiveness, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, NULL, ?, ?)",
            (name, description, file_path, json.dumps(tags or []),
             created_by, trust_tier, status, when_to_use, when_not_to_use, now, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_skill(self, name: str, description: str | None = None,
                     file_path: str | None = None, tags: list[str] | None = None,
                     status: str | None = None,
                     when_to_use: str | None = None,
                     when_not_to_use: str | None = None):
        parts, params = [], []
        for field, val in [
            ("description", description),
            ("file_path", file_path),
            ("status", status),
            ("when_to_use", when_to_use),
            ("when_not_to_use", when_not_to_use),
        ]:
            if val is not None:
                parts.append(f"{field} = ?")
                params.append(val)
        if tags is not None:
            parts.append("tags = ?")
            params.append(json.dumps(tags))
        if not parts:
            return
        parts.append("updated_at = ?")
        params.append(_now())
        params.append(name)
        self._conn.execute(
            f"UPDATE skills SET {', '.join(parts)} WHERE name = ?", params
        )
        self._conn.commit()

    def activate_skill(self, name: str):
        """Promote a draft/pending_review skill to active (Architect approval)."""
        self.update_skill(name, status="active")

    def deprecate_skill(self, name: str):
        """Mark a skill as deprecated — excluded from future assignment."""
        self.update_skill(name, status="deprecated")

    def submit_skill_for_review(self, name: str):
        """Move a draft skill to pending_review so the Architect can evaluate it."""
        self.update_skill(name, status="pending_review")

    def record_skill_outcome(self, skill_name: str, is_success: bool):
        """Record a task outcome for effectiveness tracking.

        Called after QA verdict — increments uses + (successes or failures),
        recomputes effectiveness, and auto-deprecates if below threshold.
        """
        col = "successes" if is_success else "failures"
        self._conn.execute(
            f"UPDATE skills SET uses = uses + 1, {col} = {col} + 1, updated_at = ? "
            f"WHERE name = ?",
            (_now(), skill_name),
        )
        self._conn.execute(
            "UPDATE skills SET effectiveness = CAST(successes AS REAL) / uses "
            "WHERE name = ? AND uses > 0",
            (skill_name,),
        )
        self._conn.commit()

        row = self.get_skill(skill_name)
        if row and row["trust_tier"] == "agent" and row["uses"] >= self._EFFECTIVENESS_MIN_USES:
            if row["effectiveness"] is not None and row["effectiveness"] < self._EFFECTIVENESS_DEPRECATE_THRESHOLD:
                self.deprecate_skill(skill_name)
                return f"Auto-deprecated skill '{skill_name}' (effectiveness {row['effectiveness']:.0%})"
        return None

    def get_skill(self, name: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM skills WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    def get_all_skills(self, include_inactive: bool = False) -> list[dict]:
        """Lightweight skill index for Architect assignment.

        By default returns only active skills. Set include_inactive=True
        to see draft/pending_review/deprecated skills too.
        """
        if include_inactive:
            where = ""
            params = ()
        else:
            where = "WHERE status = 'active'"
            params = ()
        rows = self._conn.execute(
            f"SELECT id, name, description, tags, trust_tier, status, "
            f"when_to_use, when_not_to_use, uses, successes, failures, effectiveness, "
            f"created_by, updated_at FROM skills {where} ORDER BY name",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_skills_by_names(self, names: list[str]) -> list[dict]:
        """Fetch full skill rows for a list of skill names.

        Only returns active skills — draft/deprecated skills are silently excluded.
        """
        if not names:
            return []
        placeholders = ",".join("?" for _ in names)
        rows = self._conn.execute(
            f"SELECT * FROM skills WHERE name IN ({placeholders}) AND status = 'active' "
            f"ORDER BY name", names
        ).fetchall()
        return [dict(r) for r in rows]

    def get_skills_pending_review(self) -> list[dict]:
        """Skills created by agents awaiting Architect approval."""
        rows = self._conn.execute(
            "SELECT id, name, description, tags, trust_tier, when_to_use, when_not_to_use, "
            "created_by, created_at FROM skills WHERE status = 'pending_review' ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def search_skills(self, keywords: str) -> list[dict]:
        """Search active skills by keyword matching in name, description, tags, when_to_use.

        Returns matching skills sorted by relevance (name match > description > tags).
        """
        tokens = [t.strip().lower() for t in keywords.replace(",", " ").split() if t.strip()]
        if not tokens:
            return []
        conditions = []
        params: list[str] = []
        for token in tokens:
            like = f"%{token}%"
            conditions.append(
                "(LOWER(name) LIKE ? OR LOWER(description) LIKE ? "
                "OR LOWER(tags) LIKE ? OR LOWER(when_to_use) LIKE ?)"
            )
            params.extend([like, like, like, like])

        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT * FROM skills WHERE status = 'active' AND ({where}) ORDER BY name",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Skill Requests ───────────────────────────────────────

    def create_skill_request(self, requested_by: str, need: str,
                             context: str = "") -> int:
        cur = self._conn.execute(
            "INSERT INTO skill_requests (requested_by, need, context, status, created_at) "
            "VALUES (?, ?, ?, 'pending', ?)",
            (requested_by, need, context, _now()),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_pending_skill_requests(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM skill_requests WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
        return [dict(r) for r in rows]

    def resolve_skill_request(self, request_id: int, resolved_skill: str | None,
                              resolution_note: str = "", status: str = "fulfilled"):
        self._conn.execute(
            "UPDATE skill_requests SET status = ?, resolved_skill = ?, "
            "resolution_note = ?, resolved_at = ? WHERE id = ?",
            (status, resolved_skill, resolution_note, _now(), request_id),
        )
        self._conn.commit()

    # ── File registry ────────────────────────────────────────

    def upsert_file(self, rel_path: str, file_type: str = "unknown",
                    size_bytes: int = 0, last_hash: str = "",
                    meta: dict | None = None):
        """Insert or update a project file entry (zero-rescan upgrades)."""
        now = _now()
        meta_json = json.dumps(meta or {})
        self._conn.execute(
            "INSERT INTO file_registry (rel_path, file_type, size_bytes, last_hash, "
            "discovered_at, updated_at, meta) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(rel_path) DO UPDATE SET "
            "file_type=excluded.file_type, size_bytes=excluded.size_bytes, "
            "last_hash=excluded.last_hash, updated_at=excluded.updated_at, "
            "meta=excluded.meta",
            (rel_path, file_type, size_bytes, last_hash, now, now, meta_json),
        )
        self._conn.commit()

    def get_file(self, rel_path: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM file_registry WHERE rel_path = ?", (rel_path,)
        ).fetchone()
        return dict(row) if row else None

    def get_files_by_type(self, file_type: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM file_registry WHERE file_type = ? ORDER BY rel_path",
            (file_type,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_files(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM file_registry ORDER BY rel_path"
        ).fetchall()
        return [dict(r) for r in rows]

    def remove_file(self, rel_path: str):
        self._conn.execute(
            "DELETE FROM file_registry WHERE rel_path = ?", (rel_path,)
        )
        self._conn.commit()

    def file_registry_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM file_registry").fetchone()
        return row[0]

    # ── Project context (key-value) ────────────────────────

    def set_project_meta(self, key: str, value: str):
        self._conn.execute(
            "INSERT INTO project_context (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, _now()),
        )
        self._conn.commit()

    def get_project_meta(self, key: str) -> str | None:
        row = self._conn.execute(
            "SELECT value FROM project_context WHERE key = ?", (key,)
        ).fetchone()
        return row[0] if row else None

    def get_all_project_meta(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT key, value FROM project_context").fetchall()
        return {r[0]: r[1] for r in rows}

    # ── Summary ─────────────────────────────────────────────

    def print_summary(self, issue_id: int):
        issue = self.get_issue(issue_id)
        if not issue:
            print(f"Issue #{issue_id} not found.")
            return
        tasks = self.get_tasks(issue_id)
        discussions = self.get_discussions(issue_id)
        ledger = self.get_ledger(issue_id)

        print(f"\n{'=' * 60}")
        print(f"  Issue #{issue_id}: {issue['objective']}")
        print(f"  Status: {issue['status']}  |  Created: {issue['created_at']}")
        if issue["current_task_id"]:
            print(f"  Current task (row id): {issue['current_task_id']}")
        print(f"{'=' * 60}")

        if discussions:
            print(f"\n  Discussion ({len(discussions)} messages):")
            for d in discussions:
                from tmb.config import get_role_name
                label = get_role_name("owner") if d["role"] in ("cto", "owner") else get_role_name("planner")
                preview = d["content"][:80].replace("\n", " ")
                print(f"    {d['created_at']}  [{label}] {preview}...")

        if tasks:
            print(f"\n  Tasks ({len(tasks)}):")
            for t in tasks:
                icon = {"pending": " ", "in_progress": "~", "completed": "x", "failed": "!", "escalated": "^"}.get(t["status"], "?")
                label = t.get("title") or t["description"][:50]
                print(f"    [{icon}] #{t['id']} [{t['branch_id']}] {label}")
                print(f"        Status: {t['status']}  |  Attempts: {t['attempts']}  |  Updated: {t['updated_at']}")

        print(f"\n  Ledger ({len(ledger)} entries):")
        for entry in ledger:
            task_str = f" [{entry['branch_id']}]" if entry.get("branch_id") else ""
            label = entry.get("summary") or entry["event_type"]
            print(f"    {entry['created_at']}  [{entry['from_node']}]{task_str}  {label}")

        print()

    # ── Markdown report ──────────────────────────────────────

    def export_report_md(self, issue_id: int) -> str:
        """Generate a full human-readable markdown report for an issue."""
        issue = self.get_issue(issue_id)
        if not issue:
            return f"Issue #{issue_id} not found."
        tasks = self.get_tasks(issue_id)
        discussions = self.get_discussions(issue_id)
        ledger = self.get_ledger(issue_id)

        completed = sum(1 for t in tasks if t["status"] == "completed")
        failed = sum(1 for t in tasks if t["status"] in ("failed", "escalated"))
        total = len(tasks)

        lines = [
            f"# Report — Issue #{issue_id}",
            "",
            f"| Field | Value |",
            f"|---|---|",
            f"| **Objective** | {issue['objective'][:120]} |",
            f"| **Status** | {issue['status']} |",
            f"| **Created** | {issue['created_at']} |",
            f"| **Closed** | {issue.get('closed_at') or '—'} |",
            f"| **Tasks** | {completed}/{total} completed, {failed} failed |",
            "",
        ]

        if discussions:
            lines += ["---", "", "## Discussion", ""]
            for d in discussions:
                from tmb.config import get_role_name
                label = get_role_name("owner") if d["role"] in ("cto", "owner") else get_role_name("planner")
                lines += [
                    f"### {label}",
                    f"*{d['created_at']}*",
                    "",
                    d["content"],
                    "",
                ]

        if tasks:
            lines += ["---", "", "## Tasks", ""]
            for t in tasks:
                icon = {"pending": "⬜", "in_progress": "🔄", "completed": "✅", "failed": "❌", "escalated": "⚠️"}.get(t["status"], "❓")
                _title_fallback, body = _split_task_description(t["description"])
                task_title = t.get("title") or _title_fallback
                lines += [
                    f"### {icon} [{t['branch_id']}] {task_title}",
                    "",
                    f"- **Status**: {t['status']}",
                    f"- **Attempts**: {t['attempts']}",
                    f"- **Success criteria**: {t['success_criteria']}",
                    f"- **Updated**: {t['updated_at']}",
                    "",
                ]
                if body:
                    lines.append("<details>")
                    lines.append("<summary>Full description</summary>")
                    lines.append("")
                    lines.append("```")
                    lines.append(body)
                    lines.append("```")
                    lines.append("")
                    lines.append("</details>")
                    lines.append("")

                task_events = [e for e in ledger if e.get("branch_id") == t["branch_id"]]
                if task_events:
                    lines.append("<details>")
                    lines.append(f"<summary>Activity log ({len(task_events)} events)</summary>")
                    lines.append("")
                    for e in task_events:
                        content_obj = json.loads(e["content"]) if e["content"] and e["content"] != "{}" else {}
                        lines.append(f"**{e['created_at']}** — `{e['from_node']}` → `{e['event_type']}`")
                        lines.append("")
                        if content_obj:
                            for k, v in content_obj.items():
                                v_str = str(v)
                                if len(v_str) > 300:
                                    v_str = v_str[:300] + "…"
                                lines.append(f"- **{k}**: {v_str}")
                            lines.append("")
                    lines.append("</details>")
                    lines.append("")

        system_events = [e for e in ledger if e.get("branch_id") is None]
        if system_events:
            lines += ["---", "", "## System Events", ""]
            lines.append("| Time | Agent | Event | Summary |")
            lines.append("|---|---|---|---|")
            for e in system_events:
                summary = e.get("summary") or e["event_type"]
                lines.append(f"| {e['created_at']} | {e['from_node']} | {e['event_type']} | {summary} |")
            lines.append("")

        token_summary = self.get_token_summary(issue_id)
        if token_summary and token_summary.get("total", {}).get("in", 0) > 0:
            lines += ["---", "", "## Token Usage", ""]
            lines.append("| Node | Input | Output |")
            lines.append("|---|---:|---:|")
            for node, counts in sorted(token_summary.items()):
                if node == "total":
                    continue
                lines.append(f"| {node} | {counts['in']:,} | {counts['out']:,} |")
            t = token_summary["total"]
            lines.append(f"| **Total** | **{t['in']:,}** | **{t['out']:,}** |")
            lines.append("")

        return "\n".join(lines)
