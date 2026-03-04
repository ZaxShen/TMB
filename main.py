"""AIDE CLI entry point.

Usage:
  uv run main.py           Run the full workflow (reads doc/GOALS.md)
  uv run main.py setup     Interactive project setup
  uv run main.py log       Show recent issues
  uv run main.py log <id>  Show issue details + ledger
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import yaml

from aide.config import _AIDE_ROOT, load_project_config, get_project_root
from aide.store import Store


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

    # Ensure doc/ exists with GOALS.md template
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

    # .env setup
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
    """Full workflow: read goals → discuss → blueprint → execute → validate."""
    project_cfg = load_project_config()
    project_root = get_project_root()
    store = Store()

    # ── Step 1: Read doc/GOALS.md ───────────────────────────
    goals_path = _AIDE_ROOT / "doc" / "GOALS.md"
    if not goals_path.exists():
        print("[AIDE] No doc/GOALS.md found. Run 'uv run main.py setup' first,")
        print("       then write your goals in doc/GOALS.md.")
        sys.exit(1)

    goals_md = goals_path.read_text().strip()
    if not goals_md or goals_md.startswith("# Goals\n\nWrite your goals"):
        print("[AIDE] doc/GOALS.md is empty or still has the template.")
        print("       Write your goals there, then run again.")
        sys.exit(1)

    # Derive a short objective from the first heading or first line
    objective_lines = [
        line for line in goals_md.splitlines()
        if line.strip() and not line.startswith("#") and not line.startswith("--") and not line.startswith("<!--")
    ]
    objective = objective_lines[0][:120] if objective_lines else "Goals from doc/GOALS.md"

    issue_id = store.create_issue(objective, goals_md)

    print(f"[AIDE] Issue #{issue_id}: {objective}")
    print(f"[AIDE] Project: {project_cfg['name']}  |  Root: {project_root}")

    # ── Step 2: Gatekeeper — scan project context ───────────
    from aide.nodes.gatekeeper import gatekeeper as run_gatekeeper
    from aide.state import AgentState

    gk_state: AgentState = {
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
    gk_result = run_gatekeeper(gk_state)
    project_context = gk_result["project_context"]

    store.log(issue_id, None, "gatekeeper", "context_scanned", {})

    # ── Step 3: Discussion — Architect ↔ CTO ────────────────
    from aide.nodes.discussion import run_discussion

    discussion_md = run_discussion(goals_md, project_context, store, issue_id)

    # ── Step 4: Blueprint — Architect plans ─────────────────
    from aide.engine import build_graph

    graph = build_graph()

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
        }
    )

    blueprint = state.get("blueprint", [])
    if not blueprint:
        print("[ARCHITECT] No blueprint was generated.")
        store.close_issue(issue_id, "failed")
        sys.exit(1)

    print()
    print(f"[ARCHITECT] Blueprint ({len(blueprint)} tasks) — see doc/BLUEPRINT.md")
    for t in blueprint:
        print(f"  {t['task_id']}. {t['description'][:80]}")
    print()

    # ── Step 5: CTO approves blueprint ──────────────────────
    approval = input("[CTO] Approve this blueprint? (yes/no): ").strip().lower()
    if approval not in ("yes", "y"):
        store.log(issue_id, None, "cto", "blueprint_rejected", {})
        store.close_issue(issue_id, "rejected")
        print("[AIDE] Blueprint rejected. Issue closed.")
        sys.exit(0)

    store.log(issue_id, None, "cto", "blueprint_approved", {})
    print()
    print("[AIDE] Blueprint approved. Starting execution...")
    print("-" * 40)

    # ── Step 6: Execute — SWE + QA loop ─────────────────────
    state = graph.invoke(state)

    store.close_issue(issue_id, "completed")

    print("-" * 40)
    store.print_summary(issue_id)
    print("[AIDE] Done. See doc/DISCUSSION.md and doc/BLUEPRINT.md for records.")


def log_history(issue_id: int | None = None):
    """Show issue history from the SQLite store."""
    store = Store()

    if issue_id:
        store.print_summary(issue_id)
    else:
        conn = store._conn
        rows = conn.execute("SELECT * FROM issues ORDER BY id DESC LIMIT 20").fetchall()
        if not rows:
            print("[AIDE] No issues found.")
            return
        print(f"\n{'=' * 60}")
        print("  Recent Issues")
        print(f"{'=' * 60}")
        for r in rows:
            icon = {"open": "o", "completed": "x", "failed": "!", "rejected": "-"}.get(r["status"], "?")
            print(f"  [{icon}] #{r['id']}  {r['objective'][:50]}  ({r['status']})")
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
