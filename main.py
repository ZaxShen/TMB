"""AIDE CLI entry point.

Usage:
  uv run main.py           Run the full workflow (reads doc/GOALS.md)
  uv run main.py setup     Interactive project setup
  uv run main.py log       Show recent issues
  uv run main.py log <id>  Show issue details + ledger
"""

from __future__ import annotations

import json
import re
import sys

import yaml

from aide.config import _AIDE_ROOT, load_project_config, get_project_root
from aide.store import Store


# ── Helpers ──────────────────────────────────────────────────


def _read_goals_md() -> str:
    """Read and clean doc/GOALS.md, stripping template boilerplate."""
    goals_path = _AIDE_ROOT / "doc" / "GOALS.md"
    if not goals_path.exists():
        goals_path.parent.mkdir(parents=True, exist_ok=True)
        goals_path.write_text(
            "# Goals\n\n"
            "Write your goals below. The Architect will read this file and discuss with you.\n\n"
            "---\n\n"
        )
        print(f"[AIDE] Created {goals_path}")
        print("       Write your goals there, then run again.")
        sys.exit(1)

    goals_raw = goals_path.read_text().strip()
    goals_md = re.sub(r"<!--.*?-->", "", goals_raw, flags=re.DOTALL).strip()
    goals_md = re.sub(
        r"^# Goals\s*\n+Write your goals.*?---\s*",
        "",
        goals_md,
        flags=re.DOTALL,
    ).strip()

    if not goals_md:
        print("[AIDE] doc/GOALS.md is empty or still has the template.")
        print("       Write your goals there, then run again.")
        sys.exit(1)

    return goals_md


def _derive_objective(goals_md: str) -> str:
    lines = [
        line
        for line in goals_md.splitlines()
        if line.strip()
        and not line.startswith("#")
        and not line.startswith("--")
        and not line.startswith("<!--")
    ]
    return lines[0][:120] if lines else "Goals from doc/GOALS.md"


def _scan_project_context(store: Store, issue_id: int, goals_md: str) -> str:
    from aide.nodes.gatekeeper import gatekeeper as run_gatekeeper

    gk_state = {
        "objective": goals_md,
        "project_context": "",
        "discussion": "",
        "issue_id": issue_id,
        "store": store,
        "blueprint": [],
        "current_task_idx": 0,
        "execution_log": "",
        "review_feedback": "",
        "iteration_count": 0,
        "messages": [],
        "next_node": "",
    }
    result = run_gatekeeper(gk_state)
    store.log(issue_id, None, "gatekeeper", "context_scanned", {})
    return result["project_context"]


def _tasks_to_blueprint(tasks: list[dict]) -> list[dict]:
    """Convert DB task rows back to the blueprint format expected by AgentState."""
    blueprint = []
    for t in tasks:
        tools = t.get("tools_required", "[]")
        if isinstance(tools, str):
            tools = json.loads(tools)
        blueprint.append(
            {
                "task_id": t["task_id"],
                "description": t["description"],
                "tools_required": tools,
                "success_criteria": t["success_criteria"],
            }
        )
    return blueprint


def _show_blueprint(tasks: list[dict]):
    print()
    print(f"[ARCHITECT] Blueprint ({len(tasks)} tasks) — see doc/BLUEPRINT.md")
    for t in tasks:
        print(f"  {t['task_id']}. {t['description'][:80]}")
    print()


def _approve_blueprint(store: Store, issue_id: int) -> bool:
    approval = input("[CTO] Approve this blueprint? (yes/no): ").strip().lower()
    if approval not in ("yes", "y"):
        store.log(issue_id, None, "cto", "blueprint_rejected", {})
        store.close_issue(issue_id, "rejected")
        print("[AIDE] Blueprint rejected. Issue closed.")
        return False

    store.log(issue_id, None, "cto", "blueprint_approved", {})
    print()
    print("[AIDE] Blueprint approved. Starting execution...")
    print("-" * 40)
    return True


def _run_execution(
    store: Store,
    issue_id: int,
    goals_md: str,
    project_context: str,
    discussion_md: str,
    blueprint: list[dict],
    start_task_idx: int,
):
    """Run the execution-only graph from a given task index."""
    from aide.engine import build_execution_graph

    graph = build_execution_graph()
    graph.invoke(
        {
            "objective": goals_md,
            "project_context": project_context,
            "discussion": discussion_md,
            "issue_id": issue_id,
            "store": store,
            "blueprint": blueprint,
            "current_task_idx": start_task_idx,
            "execution_log": "",
            "review_feedback": "",
            "iteration_count": 0,
            "messages": [],
            "next_node": "",
        }
    )

    store.close_issue(issue_id, "completed")
    print("-" * 40)
    store.print_summary(issue_id)
    print("[AIDE] Done. See doc/DISCUSSION.md and doc/BLUEPRINT.md for records.")


# ── Fresh Start ──────────────────────────────────────────────


def _fresh_start(store: Store):
    """Full workflow from scratch: goals → discuss → blueprint → approve → execute."""
    project_cfg = load_project_config()
    project_root = get_project_root()

    goals_md = _read_goals_md()
    objective = _derive_objective(goals_md)
    issue_id = store.create_issue(objective, goals_md)

    print(f"[AIDE] Issue #{issue_id}: {objective}")
    print(f"[AIDE] Project: {project_cfg['name']}  |  Root: {project_root}")

    project_context = _scan_project_context(store, issue_id, goals_md)

    from aide.nodes.discussion import run_discussion

    discussion_md = run_discussion(goals_md, project_context, store, issue_id)

    from aide.engine import build_graph

    graph = build_graph()
    thread = {"configurable": {"thread_id": f"issue-{issue_id}"}}

    state = graph.invoke(
        {
            "objective": goals_md,
            "project_context": project_context,
            "discussion": discussion_md,
            "issue_id": issue_id,
            "store": store,
            "blueprint": [],
            "current_task_idx": 0,
            "execution_log": "",
            "review_feedback": "",
            "iteration_count": 0,
            "messages": [],
            "next_node": "",
        },
        config=thread,
    )

    blueprint = state.get("blueprint", [])
    if not blueprint:
        print("[ARCHITECT] No blueprint was generated.")
        store.close_issue(issue_id, "failed")
        sys.exit(1)

    _show_blueprint(blueprint)

    if not _approve_blueprint(store, issue_id):
        sys.exit(0)

    state = graph.invoke(None, config=thread)

    store.close_issue(issue_id, "completed")
    print("-" * 40)
    store.print_summary(issue_id)
    print("[AIDE] Done. See doc/DISCUSSION.md and doc/BLUEPRINT.md for records.")


# ── Resume ───────────────────────────────────────────────────


def _resume(store: Store, issue: dict):
    """Phase router — detect where the previous run stopped and continue.

    Phases cascade: completing one phase falls through to the next.
      1. Discussion incomplete → resume discussion
      2. No tasks in DB       → run architect for blueprint + approve + execute
      3. Blueprint not approved → show blueprint, ask approval
      4. Pending/failed tasks  → resume execution from first actionable task
      5. All tasks done        → close issue
    """
    issue_id = issue["id"]
    goals_md = issue["goals_md"]
    project_cfg = load_project_config()
    project_root = get_project_root()

    print(f"[AIDE] Resuming issue #{issue_id}: {issue['objective']}")
    print(f"[AIDE] Project: {project_cfg['name']}  |  Root: {project_root}")

    project_context = None

    def ensure_context() -> str:
        nonlocal project_context
        if project_context is None:
            project_context = _scan_project_context(store, issue_id, goals_md)
        return project_context

    # Phase 1: Discussion not complete → resume it
    if not store.has_event(issue_id, "discussion_complete"):
        print("[AIDE] Phase: discussion (incomplete)")
        ctx = ensure_context()
        from aide.nodes.discussion import run_discussion

        run_discussion(goals_md, ctx, store, issue_id)

    # Phase 2: No tasks → need architect to generate blueprint
    tasks = store.get_tasks(issue_id)
    if not tasks:
        print("[AIDE] Phase: blueprint (pending)")
        ctx = ensure_context()
        discussion_md = store.export_discussion_md(issue_id)

        from aide.engine import build_graph

        graph = build_graph()
        thread = {"configurable": {"thread_id": f"issue-{issue_id}"}}

        state = graph.invoke(
            {
                "objective": goals_md,
                "project_context": ctx,
                "discussion": discussion_md,
                "issue_id": issue_id,
                "store": store,
                "blueprint": [],
                "current_task_idx": 0,
                "execution_log": "",
                "review_feedback": "",
                "iteration_count": 0,
                "messages": [],
                "next_node": "",
            },
            config=thread,
        )

        blueprint = state.get("blueprint", [])
        if not blueprint:
            print("[ARCHITECT] No blueprint was generated.")
            store.close_issue(issue_id, "failed")
            sys.exit(1)

        _show_blueprint(blueprint)

        if not _approve_blueprint(store, issue_id):
            sys.exit(0)

        # Within same process — MemorySaver still alive, resume graph
        state = graph.invoke(None, config=thread)
        store.close_issue(issue_id, "completed")
        print("-" * 40)
        store.print_summary(issue_id)
        print("[AIDE] Done. See doc/DISCUSSION.md and doc/BLUEPRINT.md for records.")
        return

    # Phase 3: Blueprint exists but not approved → show and ask
    if not store.has_event(issue_id, "blueprint_approved"):
        print("[AIDE] Phase: approval (pending)")
        _show_blueprint(tasks)
        if not _approve_blueprint(store, issue_id):
            sys.exit(0)
        # Fall through to phase 4

    # Phase 4: Approved — find first pending/failed task
    actionable = store.get_first_actionable_task(issue_id)
    if not actionable:
        print("[AIDE] All tasks already completed.")
        store.close_issue(issue_id, "completed")
        store.print_summary(issue_id)
        return

    blueprint = _tasks_to_blueprint(tasks)
    start_idx = next(
        (i for i, t in enumerate(blueprint) if t["task_id"] == actionable["task_id"]),
        0,
    )
    completed_count = sum(1 for t in tasks if t["status"] == "completed")
    total = len(tasks)

    print(
        f"[AIDE] Phase: execution (task {actionable['task_id']}/{total}, "
        f"{completed_count} already done)"
    )
    print("-" * 40)

    discussion_md = store.export_discussion_md(issue_id)
    ctx = ensure_context()
    _run_execution(store, issue_id, goals_md, ctx, discussion_md, blueprint, start_idx)


# ── CLI Commands ─────────────────────────────────────────────


def setup():
    """Interactive setup — writes config/project.yaml and .env."""
    print("[AIDE] Setup")
    print("=" * 40)
    print()

    project_root = _AIDE_ROOT / ".."
    detected_name = project_root.resolve().name

    name = input(f"Project name [{detected_name}]: ").strip() or detected_name
    test_cmd = input("Test command [pytest]: ").strip() or "pytest"
    max_retries = input("Max retries per task [3]: ").strip() or "3"

    config = {
        "name": name,
        "root_dir": "..",
        "test_command": test_cmd,
        "max_retry_per_task": int(max_retries),
    }

    config_path = _AIDE_ROOT / "config" / "project.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"  Wrote {config_path}")

    doc_dir = _AIDE_ROOT / "doc"
    goals_path = doc_dir / "GOALS.md"
    if not goals_path.exists():
        doc_dir.mkdir(parents=True, exist_ok=True)
        goals_path.write_text(
            "# Goals\n\n"
            "Write your goals below. The Architect will read this file and discuss with you.\n\n"
            "---\n\n"
        )
        print(f"  Created {goals_path}")

    env_path = _AIDE_ROOT / ".env"
    if env_path.exists():
        print(f"  .env already exists — skipping.")
    else:
        print()
        print("Which LLM provider will you use?")
        print("  1) Anthropic (Claude)")
        print("  2) OpenAI (GPT)")
        print("  3) Skip — I'll set it up later")
        choice = input("Choice [1]: ").strip() or "1"

        env_lines = []
        if choice == "1":
            key = input("ANTHROPIC_API_KEY: ").strip()
            if key:
                env_lines.append(f"ANTHROPIC_API_KEY={key}")
        elif choice == "2":
            key = input("OPENAI_API_KEY: ").strip()
            if key:
                env_lines.append(f"OPENAI_API_KEY={key}")

        if env_lines:
            env_path.write_text("\n".join(env_lines) + "\n")
            print(f"  Wrote {env_path}")
        else:
            print("  Skipped .env — set your API key before running.")

    print()
    print("[AIDE] Setup complete.")
    print("  1. Write your goals in doc/GOALS.md")
    print("  2. Run: uv run main.py")
    print()


def run():
    """Phase-aware entry point: resumes an open issue or starts fresh."""
    store = Store()
    existing = store.get_open_issue()

    if existing:
        goals_md = _read_goals_md()

        if goals_md != existing["goals_md"]:
            print(
                f"[AIDE] GOALS.md has changed since issue #{existing['id']} was started."
            )
            choice = (
                input("  (c)ontinue old issue / (n)ew issue? ").strip().lower()
            )
            if choice in ("n", "new"):
                store.close_issue(existing["id"], "superseded")
                existing = None

    if existing:
        _resume(store, existing)
    else:
        _fresh_start(store)


def log_history(issue_id: int | None = None):
    """Show issue history from the SQLite store."""
    store = Store()

    if issue_id:
        store.print_summary(issue_id)
    else:
        conn = store._conn
        rows = conn.execute(
            "SELECT * FROM issues ORDER BY id DESC LIMIT 20"
        ).fetchall()
        if not rows:
            print("[AIDE] No issues found.")
            return
        print(f"\n{'=' * 60}")
        print("  Recent Issues")
        print(f"{'=' * 60}")
        for r in rows:
            icon = {
                "open": "o",
                "completed": "x",
                "failed": "!",
                "rejected": "-",
                "superseded": "~",
            }.get(r["status"], "?")
            print(
                f"  [{icon}] #{r['id']}  {r['objective'][:50]}  ({r['status']})"
            )
        print()
        print("  View details: uv run main.py log <issue_id>")
        print()


def main():
    if len(sys.argv) == 1:
        run()
        return

    cmd = sys.argv[1]

    if cmd == "setup":
        setup()
    elif cmd == "log":
        issue_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
        log_history(issue_id)
    else:
        print("AIDE — AI Direction & Execution")
        print()
        print("Usage:")
        print("  uv run main.py              Run workflow (reads doc/GOALS.md)")
        print("  uv run main.py setup        Interactive project setup")
        print("  uv run main.py log          Show recent issues")
        print("  uv run main.py log <id>     Show issue details + ledger")
        sys.exit(1)


if __name__ == "__main__":
    main()
