"""SQLite audit store — full workflow history.

Tables:
  issues       — CTO objectives (from doc/GOALS.md)
  discussions  — Architect-CTO Q&A exchanges (kept permanently, doc/DISCUSSION.md is overwritten)
  tasks        — Blueprint items assigned to Executor
  ledger       — Append-only log of every agent action

Write boundary: agents may ONLY write to doc/DISCUSSION.md, doc/BLUEPRINT.md, and this DB.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_DB_NAME = "aide_history.db"

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
            from aide.config import _AIDE_ROOT
            db_path = _AIDE_ROOT / _DB_NAME
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS issues (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                objective       TEXT    NOT NULL,
                goals_md        TEXT    NOT NULL DEFAULT '',
                status          TEXT    NOT NULL DEFAULT 'open',
                current_task_id INTEGER REFERENCES tasks(id),
                created_at      TEXT    NOT NULL,
                updated_at      TEXT    NOT NULL,
                closed_at       TEXT
            );

            CREATE TABLE IF NOT EXISTS discussions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id    INTEGER NOT NULL REFERENCES issues(id),
                role        TEXT    NOT NULL,
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id         INTEGER NOT NULL REFERENCES issues(id),
                task_id          INTEGER NOT NULL,
                description      TEXT    NOT NULL,
                tools_required   TEXT    NOT NULL DEFAULT '[]',
                success_criteria TEXT    NOT NULL,
                status           TEXT    NOT NULL DEFAULT 'pending',
                attempts         INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT    NOT NULL,
                updated_at       TEXT    NOT NULL,
                completed_at     TEXT
            );

            CREATE TABLE IF NOT EXISTS ledger (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                issue_id    INTEGER NOT NULL REFERENCES issues(id),
                task_id     INTEGER,
                from_node   TEXT    NOT NULL,
                event_type  TEXT    NOT NULL,
                content     TEXT    NOT NULL DEFAULT '{}',
                created_at  TEXT    NOT NULL
            );
        """)

    # ── Issues ──────────────────────────────────────────────

    def create_issue(self, objective: str, goals_md: str = "") -> int:
        now = _now()
        cur = self._conn.execute(
            "INSERT INTO issues (objective, goals_md, status, created_at, updated_at) VALUES (?, ?, 'open', ?, ?)",
            (objective, goals_md, now, now),
        )
        self._conn.commit()
        issue_id = cur.lastrowid
        self.log(issue_id, None, "cto", "issue_opened", {"objective": objective})
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
        self.log(issue_id, None, "system", "issue_closed", {"status": status})

    def get_issue(self, issue_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM issues WHERE id = ?", (issue_id,)).fetchone()
        return dict(row) if row else None

    def get_open_issue(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM issues WHERE status = 'open' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

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
            "SELECT * FROM tasks WHERE issue_id = ? AND status IN ('pending', 'failed', 'in_progress', 'escalated') ORDER BY task_id LIMIT 1",
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
        """Export current discussion as Markdown. This overwrites doc/DISCUSSION.md
        each time — previous discussions are preserved only in the DB."""
        issue = self.get_issue(issue_id)
        discussions = self.get_discussions(issue_id)
        lines = [
            f"# Discussion — Issue #{issue_id}",
            "",
            f"> This file reflects the **current** discussion only.",
            f"> Previous discussions are preserved in `aide_history.db`.",
            "",
            f"**Objective**: {issue['objective']}",
            f"**Date**: {issue['created_at']}",
            "",
            "---",
            "",
        ]
        for d in discussions:
            label = "**CTO**" if d["role"] == "cto" else "**Architect**"
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
        if existing:
            self._conn.execute(
                "DELETE FROM tasks WHERE issue_id = ?", (issue_id,)
            )
            self.log(issue_id, None, "architect", "blueprint_superseded", {
                "old_task_count": len(existing),
            })

        for task in blueprint:
            self._conn.execute(
                "INSERT INTO tasks (issue_id, task_id, description, tools_required, success_criteria, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                (
                    issue_id,
                    task["task_id"],
                    task["description"],
                    json.dumps(task.get("tools_required", [])),
                    task["success_criteria"],
                    now,
                    now,
                ),
            )
        self._conn.commit()
        self.log(issue_id, None, "architect", "blueprint_created", {
            "task_count": len(blueprint),
            "tasks": [{"task_id": t["task_id"], "description": t["description"]} for t in blueprint],
        })

    def update_task_status(self, issue_id: int, task_id: int, status: str, increment_attempts: bool = False):
        now = _now()
        if increment_attempts:
            self._conn.execute(
                "UPDATE tasks SET status = ?, attempts = attempts + 1, updated_at = ? WHERE issue_id = ? AND task_id = ?",
                (status, now, issue_id, task_id),
            )
        else:
            updates = "status = ?, updated_at = ?"
            params: list[Any] = [status, now]
            if status == "completed":
                updates += ", completed_at = ?"
                params.append(now)
            params.extend([issue_id, task_id])
            self._conn.execute(
                f"UPDATE tasks SET {updates} WHERE issue_id = ? AND task_id = ?",
                params,
            )
        self._conn.commit()

        # Update issue's current_task_id pointer
        row = self._conn.execute(
            "SELECT id FROM tasks WHERE issue_id = ? AND task_id = ?", (issue_id, task_id)
        ).fetchone()
        if row:
            self.update_issue_current_task(issue_id, row["id"])

    def get_tasks(self, issue_id: int) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM tasks WHERE issue_id = ? ORDER BY task_id", (issue_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_task_row(self, issue_id: int, task_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE issue_id = ? AND task_id = ?", (issue_id, task_id)
        ).fetchone()
        return dict(row) if row else None

    def export_blueprint_md(self, issue_id: int, blueprint: list[dict]) -> str:
        issue = self.get_issue(issue_id)
        now = _now()
        lines = [
            f"# Blueprint — Issue #{issue_id}",
            "",
            f"**Objective**: {issue['objective']}",
            f"**Date**: {now}",
            f"**Tasks**: {len(blueprint)}",
            "",
            "---",
            "",
        ]
        for t in blueprint:
            lines.append(f"## Task {t['task_id']}: {t['description']}")
            lines.append("")
            lines.append(f"- **Tools**: {', '.join(t.get('tools_required', []))}")
            lines.append(f"- **Success criteria**: {t['success_criteria']}")
            lines.append("")
        return "\n".join(lines)

    # ── Ledger ──────────────────────────────────────────────

    def log(self, issue_id: int, task_id: int | None, from_node: str, event_type: str, content: dict | str = ""):
        if isinstance(content, dict):
            content = json.dumps(content)
        self._conn.execute(
            "INSERT INTO ledger (issue_id, task_id, from_node, event_type, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (issue_id, task_id, from_node, event_type, content, _now()),
        )
        self._conn.commit()

    def get_ledger(self, issue_id: int, task_id: int | None = None) -> list[dict]:
        if task_id is not None:
            rows = self._conn.execute(
                "SELECT * FROM ledger WHERE issue_id = ? AND task_id = ? ORDER BY id",
                (issue_id, task_id),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM ledger WHERE issue_id = ? ORDER BY id", (issue_id,)
            ).fetchall()
        return [dict(r) for r in rows]

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
                label = "CTO" if d["role"] == "cto" else "Architect"
                preview = d["content"][:80].replace("\n", " ")
                print(f"    {d['created_at']}  [{label}] {preview}...")

        if tasks:
            print(f"\n  Tasks ({len(tasks)}):")
            for t in tasks:
                icon = {"pending": " ", "in_progress": "~", "completed": "x", "failed": "!", "escalated": "^"}.get(t["status"], "?")
                print(f"    [{icon}] #{t['id']} Task {t['task_id']}: {t['description'][:50]}")
                print(f"        Status: {t['status']}  |  Attempts: {t['attempts']}  |  Updated: {t['updated_at']}")

        print(f"\n  Ledger ({len(ledger)} entries):")
        for entry in ledger:
            task_str = f" Task {entry['task_id']}" if entry["task_id"] else ""
            print(f"    {entry['created_at']}  [{entry['from_node']}]{task_str}  {entry['event_type']}")

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
                label = "CTO" if d["role"] == "cto" else "Architect"
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
                title, body = _split_task_description(t["description"])
                lines += [
                    f"### {icon} Task {t['task_id']}: {title}",
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

                task_events = [e for e in ledger if e["task_id"] == t["task_id"]]
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

        system_events = [e for e in ledger if e["task_id"] is None]
        if system_events:
            lines += ["---", "", "## System Events", ""]
            lines.append("| Time | Agent | Event |")
            lines.append("|---|---|---|")
            for e in system_events:
                lines.append(f"| {e['created_at']} | {e['from_node']} | {e['event_type']} |")
            lines.append("")

        return "\n".join(lines)
