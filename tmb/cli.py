"""TMB CLI entry point.

Usage:
  tmb                               Chat mode (default — ask anything)
  tmb plan                          Full planning workflow (reads bro/GOALS.md)
  tmb chat                          Chat mode (explicit)
  tmb evolve "instruction"          Self-evolution (modify TMB itself)
  tmb setup                         Interactive project setup
  tmb scan                          Scan project for TMB context
  tmb log                           Show recent issues
  tmb log <id>                      Show issue details + ledger
  tmb report <id>                   Export full report as markdown
  tmb serve                         Start MCP server (stdio)
  tmb serve --http 8080             Start MCP server (HTTP)
"""

from __future__ import annotations

# Suppress Pydantic V1 compat warning on Python 3.14+
# (LangChain's transitive deps still use pydantic.v1 — harmless until they migrate)
import warnings
warnings.filterwarnings("ignore", message=".*Pydantic V1.*")

import difflib
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from tmb.config import load_project_config, get_project_root, get_role_name
from tmb.paths import TMB_ROOT, SYSTEM_PROMPTS_DIR, SAMPLES_DIR, docs_dir, runtime_dir, user_cfg_dir, user_prompts_dir, ensure_dirs
from tmb.utils import truncate, fit_line
from tmb.scanner import detect_tech_stack, read_key_docs
from tmb.store import Store


# ── Helpers ──────────────────────────────────────────────────


def _read_goals_md() -> str:
    """Read and clean GOALS.md from bro/, stripping template boilerplate."""
    goals_path = docs_dir() / "GOALS.md"
    if not goals_path.exists():
        goals_path.parent.mkdir(parents=True, exist_ok=True)
        goals_path.write_text(
            "# Goals\n\n"
            "Write your goals below. The Planner will read this file and discuss with you.\n\n"
            "---\n\n"
        )
        print(f"[TMB] 📝 Created {goals_path}")
        from tmb.ux import open_in_editor, wait_for_file_change
        open_in_editor(goals_path)
        print(f"[TMB] Write your goals in {goals_path.name}, then save the file.")
        if not wait_for_file_change(goals_path):
            print("[TMB] No changes detected. Write your goals and run again.")
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
        print(f"[TMB] {goals_path.name} is empty — opening for you to fill in.")
        from tmb.ux import open_in_editor, wait_for_file_change
        open_in_editor(goals_path)
        print(f"[TMB] Write your goals in {goals_path.name}, then save the file.")
        if not wait_for_file_change(goals_path):
            print("[TMB] No changes detected. Write your goals and run again.")
            sys.exit(1)
        # Re-read after save
        goals_raw = goals_path.read_text().strip()
        goals_md = re.sub(r"<!--.*?-->", "", goals_raw, flags=re.DOTALL).strip()
        goals_md = re.sub(
            r"^# Goals\s*\n+Write your goals.*?---\s*",
            "",
            goals_md,
            flags=re.DOTALL,
        ).strip()
        if not goals_md:
            print("[TMB] Goals still empty after save. Write your goals and run again.")
            sys.exit(1)

    return goals_md


def _check_stale_goals(store: Store, goals_md: str) -> bool:
    """Check if current goals match or closely resemble a completed issue.

    Returns True if the user should NOT proceed (stale/duplicate goals detected).
    Returns False if the user should proceed normally.
    """
    goals_hash = hashlib.md5(goals_md.encode()).hexdigest()

    # Tier 1: Exact match via MD5 hash
    exact = store.find_completed_by_goals_hash(goals_hash)
    if exact:
        print(f"\n[TMB] ✅ Issue #{exact['id']} already completed these goals.")
        print(f"[TMB]    Status: {exact['status']}  |  {exact['objective']}")
        print(f"[TMB]    To start new work, update GOALS.md with new goals.")
        _cleanup_completed_issue(store, exact["id"], store.get_tasks(exact["id"]))
        return True

    # Tier 2: Near-match via similarity (length pre-filter + SequenceMatcher)
    recent = store.get_recent_completed_issues(5)
    if not recent:
        return False

    goals_len = len(goals_md)
    for issue in recent:
        prev_goals = issue.get("goals_md", "")
        if not prev_goals:
            continue

        # Quick pre-filter: if char count differs by >50%, skip (clearly different)
        prev_len = len(prev_goals)
        if prev_len == 0:
            continue
        length_ratio = min(goals_len, prev_len) / max(goals_len, prev_len)
        if length_ratio < 0.5:
            continue

        # SequenceMatcher for actual content similarity
        ratio = difflib.SequenceMatcher(None, goals_md, prev_goals).ratio()
        if ratio > 0.85:
            pct = int(ratio * 100)
            print(f"\n[TMB] ⚠️  These goals look {pct}% similar to completed issue #{issue['id']}.")
            print(f"[TMB]    Issue #{issue['id']}: {issue['objective']}")
            choice = input("  (c)ontinue with new issue / (u)pdate GOALS.md first? ").strip().lower()
            if choice in ("u", "update"):
                print("[TMB] Update GOALS.md with new goals, then run again.")
                return True
            # User chose to continue — don't check remaining issues
            return False

    return False


def _derive_objective(goals_md: str) -> str:
    lines = [
        line
        for line in goals_md.splitlines()
        if line.strip()
        and not line.startswith("#")
        and not line.startswith("--")
        and not line.startswith("<!--")
    ]
    return lines[0][:120] if lines else "Goals from GOALS.md"


def _scan_project_context(store: Store, issue_id: int, goals_md: str) -> str:
    from tmb.nodes.gatekeeper import gatekeeper as run_gatekeeper

    gk_state = {
        "objective": goals_md,
        "project_context": "",
        "discussion": "",
        "issue_id": issue_id,
        "blueprint": [],
        "current_task_idx": 0,
        "execution_log": "",
        "review_feedback": "",
        "iteration_count": 0,
        "messages": [],
        "next_node": "",
    }
    result = run_gatekeeper(gk_state)
    store.log(issue_id, None, "gatekeeper", "context_scanned", {},
              summary="Scanned project directory tree")
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
                "branch_id": str(t["branch_id"]),
                "title": t.get("title", ""),
                "description": t["description"],
                "tools_required": tools,
                "success_criteria": t["success_criteria"],
            }
        )
    return blueprint


def _show_blueprint(tasks: list[dict]):
    print()
    planner_display = get_role_name("planner").upper()
    print(f"[{planner_display}] 📋 Blueprint ({len(tasks)} tasks) — see bro/BLUEPRINT.md")
    for t in tasks:
        bid = t.get("branch_id") or t.get("task_id", "?")
        desc = t.get("title") or t.get("description", "")
        print(fit_line(f"  [{bid}]", desc))
    print()
    # Auto-open blueprint for review
    from tmb.ux import open_in_editor
    blueprint_path = docs_dir() / "BLUEPRINT.md"
    if blueprint_path.exists():
        open_in_editor(blueprint_path)


def _invoke_with_monitor(graph, state_or_none, config, store, issue_id):
    """Run graph.invoke() with live dashboard monitoring.

    Redirects node stdout to a buffer, polls SQLite from a background thread,
    and renders the dashboard to the real terminal. Falls back to normal invoke
    if not running in a terminal.
    """
    from tmb.monitor import is_terminal, run_monitor_loop

    if not is_terminal():
        if state_or_none is None:
            return graph.invoke(None, config=config)
        return graph.invoke(state_or_none, config=config)

    import io
    import threading
    from tmb.paths import db_path

    real_stdout = sys.stdout
    captured = io.StringIO()
    stop_event = threading.Event()

    monitor_thread = threading.Thread(
        target=run_monitor_loop,
        args=(str(db_path()), issue_id, stop_event, real_stdout),
        daemon=True,
    )

    try:
        sys.stdout = captured
        monitor_thread.start()
        if state_or_none is None:
            result = graph.invoke(None, config=config)
        else:
            result = graph.invoke(state_or_none, config=config)
    finally:
        stop_event.set()
        sys.stdout = real_stdout
        if monitor_thread.is_alive():
            monitor_thread.join(timeout=3)

    # Final render
    from tmb.monitor import clear_and_render
    clear_and_render(store, issue_id)

    return result


def _approve_blueprint(store: Store, issue_id: int) -> bool:
    owner_display = get_role_name("owner")
    approval = input(f"[{owner_display}] Approve this blueprint? (yes/no): ").strip().lower()
    if approval not in ("yes", "y"):
        store.log(issue_id, None, "owner", "blueprint_rejected", {},
                  summary=f"{owner_display} rejected blueprint")
        store.close_issue(issue_id, "rejected")
        print("[TMB] ❌ Blueprint rejected. Issue closed.")
        return False

    store.log(issue_id, None, "owner", "blueprint_approved", {},
              summary=f"{owner_display} approved blueprint")
    print()
    print("[TMB] ✅ Blueprint approved. Generating execution plan...")
    print("-" * 40)
    return True


def _maybe_suggest_scan(store: Store, project_root) -> None:
    """Suggest running 'tmb scan' if the project hasn't been scanned yet."""
    try:
        count = store._conn.execute("SELECT COUNT(*) FROM file_registry").fetchone()[0]
        if count == 0:
            print("[TMB] 💡 Tip: run `bro scan` first for better results (scans your project for context).")
    except Exception:
        # Table might not exist yet — that's fine, skip silently
        pass


def _quick_task(store: Store, instruction: str):
    """Quick-task flow: same pipeline as full workflow, minus discussion and manual approval.

    gatekeeper → planner_plan (auto-approved) → execution plans → executor ↔ planner_validate
    """
    project_cfg = load_project_config()
    project_root = get_project_root()

    _maybe_suggest_scan(store, project_root)

    objective = instruction[:120].strip()
    issue_id = store.create_issue(objective, instruction)

    # Git pre-snapshot for rollback
    from tmb.git import ensure_repo, snapshot
    project_root_path = Path(project_root) if not isinstance(project_root, Path) else project_root
    ensure_repo(project_root_path)
    pre_hash = snapshot(project_root_path, f"tmb: snapshot before Issue #{issue_id}")
    if pre_hash:
        store.set_pre_commit_hash(issue_id, pre_hash)

    print(f"[TMB] ⚡ Quick task — Issue #{issue_id}: {objective}")
    print(f"[TMB] Project: {project_cfg['name']}  |  Root: {project_root}")
    print("-" * 40)

    project_context = _scan_project_context(store, issue_id, instruction)

    from tmb.engine import build_graph

    graph = build_graph()
    thread = {"configurable": {"thread_id": f"issue-{issue_id}"}}

    state = graph.invoke(
        {
            "objective": instruction,
            "project_context": project_context,
            "discussion": "",
            "issue_id": issue_id,
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
        print(f"[{get_role_name('planner').upper()}] ⚠️ No blueprint was generated.")
        store.close_issue(issue_id, "failed")
        return

    _show_blueprint(blueprint)

    store.log(issue_id, None, "owner", "blueprint_approved", {},
              summary="Auto-approved (quick task)")
    print("[TMB] ✅ Blueprint auto-approved (quick task)")
    print("-" * 40)

    state = _invoke_with_monitor(graph, None, thread, store, issue_id)

    _finalize_issue(store, issue_id)


def _scan_tmb_context(store: Store, issue_id: int, instruction: str) -> str:
    """Scan the TMB directory itself (not the project) for self-evolution."""
    from tmb.nodes.gatekeeper import _get_tree, _read_key_files

    tree = _get_tree(TMB_ROOT)
    key_files = _read_key_files(TMB_ROOT)

    context = (
        f"## TMB Framework\n"
        f"## Root: {TMB_ROOT}\n\n"
        f"### Directory structure\n```\n{tree}\n```\n\n"
        f"### Key files\n{key_files}\n"
    )
    store.log(issue_id, None, "gatekeeper", "tmb_context_scanned", {},
              summary="Scanned TMB directory tree for self-evolution")
    print(f"[GATEKEEPER] ✅ Scanned {len(tree.splitlines())} paths in TMB/")
    return context


_EVOLVE_WARNING = """
╔══════════════════════════════════════════════════════════════╗
║                  ⚠  SELF-EVOLUTION MODE  ⚠                  ║
║                                                              ║
║  Agents will have FULL READ/WRITE access to TMB source.     ║
║  A git snapshot will be created before any changes.          ║
║                                                              ║
║  Rollback: git revert HEAD  (after evolution completes)      ║
╚══════════════════════════════════════════════════════════════╝
"""


def _git_snapshot(instruction: str) -> bool:
    """Commit current TMB state as a safety snapshot before self-evolution.
    Returns True if a snapshot was created, False if tree was already clean."""
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(TMB_ROOT), capture_output=True, text=True, timeout=10,
        )
        if not status.stdout.strip():
            print("[EVOLVE] ✅ Working tree clean — no snapshot needed.")
            return False

        subprocess.run(
            ["git", "add", "-A"],
            cwd=str(TMB_ROOT), check=True, timeout=10,
        )
        msg = f"TMB snapshot before self-evolution: {instruction[:80]}"
        subprocess.run(
            ["git", "commit", "-m", msg],
            cwd=str(TMB_ROOT), check=True, capture_output=True, timeout=15,
        )
        print(f"[EVOLVE] 📸 Git snapshot committed: {msg}")
        return True
    except Exception as e:
        print(f"[EVOLVE] ⚠️ Warning: git snapshot failed ({e}). Proceeding anyway.")
        return False


def _health_check() -> bool:
    """Verify TMB can still be imported after self-evolution."""
    print("[EVOLVE] 🧪 Running health check...")
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import tmb; import tmb.engine; import tmb.store"],
            cwd=str(TMB_ROOT), capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"[EVOLVE] ❌ HEALTH CHECK FAILED — import error:")
            print(result.stderr[:500])
            return False
    except Exception as e:
        print(f"[EVOLVE] ❌ HEALTH CHECK FAILED — {e}")
        return False

    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "tmb/"],
            cwd=str(TMB_ROOT), capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            warnings = result.stdout[:500] if result.stdout else result.stderr[:500]
            print(f"[EVOLVE] Lint warnings (non-blocking):\n{warnings}")
    except Exception:
        pass

    print("[EVOLVE] ✅ Health check passed.")
    return True


def _evolve(store: Store, instruction: str):
    """Self-evolution flow: scan TMB → Planner plans → Owner approves
    → git snapshot → Planner executes → health check."""
    from tmb.permissions import evolve_context

    print(_EVOLVE_WARNING)

    objective = f"[EVOLVE] {instruction[:100].strip()}"
    issue_id = store.create_issue(objective, instruction)
    store.log(issue_id, None, "system", "evolve_started", {
        "instruction": instruction,
    }, summary=f"Self-evolution started: {instruction[:120]}")

    print(f"[EVOLVE] Issue #{issue_id}: {objective}")
    print("-" * 60)

    with evolve_context():
        tmb_context = _scan_tmb_context(store, issue_id, instruction)

    with evolve_context():
        from tmb.nodes.planner import planner_evolve
        plan = planner_evolve(instruction, tmb_context, issue_id)

    if not plan or not plan.strip():
        print("[EVOLVE] ⚠️ Planner produced no plan. Aborting.")
        store.close_issue(issue_id, "failed")
        return

    owner_display = get_role_name("owner")
    print()
    print("=" * 60)
    print("[EVOLVE] Review the evolution plan in doc/EVOLUTION.md")
    print("         Press Enter to APPROVE, or Ctrl+C to abort.")
    print("=" * 60)
    try:
        input()
    except (KeyboardInterrupt, EOFError):
        print(f"\n[EVOLVE] Aborted by {owner_display}.")
        store.log(issue_id, None, "owner", "evolve_rejected", {},
                  summary=f"{owner_display} aborted self-evolution")
        store.close_issue(issue_id, "rejected")
        return

    store.log(issue_id, None, "owner", "evolve_approved", {},
              summary=f"{owner_display} approved evolution plan")

    _git_snapshot(instruction)

    with evolve_context():
        from tmb.nodes.planner import planner_evolve_execute
        result = planner_evolve_execute(instruction, plan, tmb_context, issue_id)

    healthy = _health_check()

    if healthy:
        store.log(issue_id, None, "system", "evolve_completed", {},
                  summary=f"Self-evolution completed: {instruction[:120]}")
        store.close_issue(issue_id, "completed")
        print()
        print("-" * 60)
        print(f"[EVOLVE] 🎉 Self-evolution complete. Issue #{issue_id} closed.")
    else:
        store.log(issue_id, None, "system", "evolve_failed", {},
                  summary=f"Self-evolution failed health check: {instruction[:120]}")
        store.close_issue(issue_id, "failed")
        print()
        print("!" * 60)
        print("[EVOLVE] ❌ HEALTH CHECK FAILED. Your changes may have broken TMB.")
        print("[EVOLVE] 🔄 To rollback:  cd TMB && git revert HEAD")
        print("!" * 60)

    if result:
        print()
        print(result[:800])
    print()


def _print_token_summary(store: Store, issue_id: int):
    """Print a compact token usage report for the issue."""
    summary = store.get_token_summary(issue_id)
    if not summary or summary.get("total", {}).get("in", 0) == 0:
        return
    print()
    print(f"Token Usage — Issue #{issue_id}")
    for node, counts in sorted(summary.items()):
        if node == "total":
            continue
        print(f"  {node:20s}  {counts['in']:>9,} in / {counts['out']:>9,} out")
    t = summary["total"]
    print(f"  {'total':20s}  {t['in']:>9,} in / {t['out']:>9,} out")


def _cleanup_completed_issue(store: Store, issue_id: int, tasks: list[dict]):
    """Reset GOALS.md and DISCUSSION.md after successful issue completion."""
    dd = docs_dir()
    dd.mkdir(parents=True, exist_ok=True)

    # Print completion summary with verification hints
    criteria = [t["success_criteria"] for t in tasks if t.get("success_criteria")]
    print()
    print(f"[TMB] Issue #{issue_id} completed — all {len(tasks)} task(s) passed.")
    if criteria:
        print("[TMB] Verify your results:")
        for i, c in enumerate(criteria, 1):
            print(f"  [{i}] {c}")

    # Reset GOALS.md to clean template
    goals_path = dd / "GOALS.md"
    goals_path.write_text(
        "# Goals\n\n"
        f"<!-- Issue #{issue_id} completed successfully. -->\n\n"
        "Write your goals below. The Planner will read this file and discuss with you.\n\n"
        "---\n\n"
    )

    # Reset DISCUSSION.md
    disc_path = dd / "DISCUSSION.md"
    disc_path.write_text(
        "# Discussion\n\n"
        "(New discussion will appear here when you run tmb with new goals.)\n"
    )


def _auto_commit_completed(store: Store, issue_id: int, tasks: list[dict]):
    """Auto-commit project state after successful issue completion."""
    try:
        from tmb.git import snapshot, get_diff_summary, build_commit_message
        project_root = Path(get_project_root())

        issue = store.get_issue(issue_id)
        if not issue:
            return

        diff_summary = get_diff_summary(project_root)
        msg = build_commit_message(
            issue_id, issue["objective"], tasks, diff_summary
        )
        commit_hash = snapshot(project_root, msg)
        if commit_hash:
            store.log(
                issue_id, None, "system", "auto_committed",
                {"commit_hash": commit_hash},
                summary=f"Auto-committed: {commit_hash}",
            )
            print(f"[TMB] Committed: {commit_hash}")
    except Exception:
        pass  # Auto-commit is best-effort — never block completion


def _finalize_issue(store: Store, issue_id: int):
    """Check task statuses and close the issue appropriately."""
    tasks = store.get_tasks(issue_id)
    if not tasks:
        store.close_issue(issue_id, "completed")
        _cleanup_completed_issue(store, issue_id, [])
        _auto_commit_completed(store, issue_id, [])
        return

    all_done = all(t["status"] == "completed" for t in tasks)
    if all_done:
        store.close_issue(issue_id, "completed")
        _cleanup_completed_issue(store, issue_id, tasks)
        _auto_commit_completed(store, issue_id, tasks)
    else:
        stuck = [t for t in tasks if t["status"] in ("failed", "escalated")]
        pending = [t for t in tasks if t["status"] in ("pending", "in_progress")]
        if stuck:
            print(
                f"[TMB] ❌ {len(stuck)} task(s) failed/escalated. "
                f"Issue #{issue_id} stays open — re-run to retry."
            )
        elif pending:
            print(
                f"[TMB] ⏳ {len(pending)} task(s) still pending. "
                f"Issue #{issue_id} stays open — re-run to continue."
            )

    print("-" * 40)
    store.print_summary(issue_id)
    _print_token_summary(store, issue_id)
    dd = docs_dir()
    doc_names = [f.stem for f in sorted(dd.glob("*.md")) if f.stem != "GOALS"]
    if doc_names:
        print(f"[TMB] See {dd.name}/ for {', '.join(doc_names)}.")
    else:
        print(f"[TMB] See {dd.name}/ for generated docs.")


def _run_execution_plan(
    store: Store,
    issue_id: int,
    goals_md: str,
    project_context: str,
    blueprint: list[dict],
):
    """Generate EXECUTION.md by calling planner_execution_plan directly."""
    from tmb.nodes.planner import planner_execution_plan

    state = {
        "objective": goals_md,
        "project_context": project_context,
        "discussion": "",
        "issue_id": issue_id,
        "blueprint": blueprint,
        "current_task_idx": 0,
        "execution_log": "",
        "review_feedback": "",
        "iteration_count": 0,
        "messages": [],
        "next_node": "",
    }
    planner_execution_plan(state)


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
    from tmb.engine import build_execution_graph

    graph = build_execution_graph()
    _invoke_with_monitor(
        graph,
        {
            "objective": goals_md,
            "project_context": project_context,
            "discussion": discussion_md,
            "issue_id": issue_id,
            "blueprint": blueprint,
            "current_task_idx": start_task_idx,
            "execution_log": "",
            "review_feedback": "",
            "iteration_count": 0,
            "messages": [],
            "next_node": "",
        },
        None,
        store,
        issue_id,
    )

    _finalize_issue(store, issue_id)


# ── Fresh Start ──────────────────────────────────────────────


def _auto_sync_registry(store: Store, project_root):
    """Fast file-registry sync — keeps bro aware of the latest project structure."""
    from tmb.scanner import sync_file_registry

    count = sync_file_registry(Path(project_root), store)
    if count == 0:
        return

    changed = store.get_changed_files()
    if changed:
        added = sum(1 for f in changed if f["change_type"] == "added")
        modified = sum(1 for f in changed if f["change_type"] == "modified")
        parts = []
        if added:
            parts.append(f"+{added}")
        if modified:
            parts.append(f"~{modified}")
        delta = ", ".join(parts) if parts else "no changes"
        print(f"[TMB] 📂 File registry synced ({count} files, {delta})")
    else:
        print(f"[TMB] 📂 File registry synced ({count} files)")


def _fresh_start(store: Store):
    """Full workflow: goals → discuss → plan (blueprint + flowchart) → approve → execution plan → execute."""
    project_cfg = load_project_config()
    project_root = get_project_root()

    _auto_sync_registry(store, project_root)

    goals_md = _read_goals_md()
    objective = _derive_objective(goals_md)
    issue_id = store.create_issue(objective, goals_md)

    # Git pre-snapshot for rollback
    from tmb.git import ensure_repo, snapshot
    project_root_path = Path(project_root) if not isinstance(project_root, Path) else project_root
    ensure_repo(project_root_path)
    pre_hash = snapshot(project_root_path, f"tmb: snapshot before Issue #{issue_id}")
    if pre_hash:
        store.set_pre_commit_hash(issue_id, pre_hash)

    print(f"[TMB] Issue #{issue_id}: {objective}")
    print(f"[TMB] Project: {project_cfg['name']}  |  Root: {project_root}")

    project_context = _scan_project_context(store, issue_id, goals_md)

    from tmb.nodes.discussion import run_discussion

    discussion_md = run_discussion(goals_md, project_context, store, issue_id)

    from tmb.engine import build_graph

    graph = build_graph()
    thread = {"configurable": {"thread_id": f"issue-{issue_id}"}}

    state = graph.invoke(
        {
            "objective": goals_md,
            "project_context": project_context,
            "discussion": discussion_md,
            "issue_id": issue_id,
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
        print(f"[{get_role_name('planner').upper()}] ⚠️ No blueprint was generated.")
        store.close_issue(issue_id, "failed")
        sys.exit(1)

    _show_blueprint(blueprint)
    dd = docs_dir()
    review = [f"{dd.name}/BLUEPRINT.md"]
    if (dd / "FLOWCHART.md").exists():
        review.append(f"{dd.name}/FLOWCHART.md")
    print(f"[TMB] Review {' and '.join(review)}")
    print()

    if not _approve_blueprint(store, issue_id):
        sys.exit(0)

    state = _invoke_with_monitor(graph, None, thread, store, issue_id)

    _finalize_issue(store, issue_id)


# ── Resume ───────────────────────────────────────────────────


def _resume(store: Store, issue: dict):
    """Phase router — detect where the previous run stopped and continue."""
    issue_id = issue["id"]
    goals_md = issue["goals_md"]
    project_cfg = load_project_config()
    project_root = get_project_root()

    _auto_sync_registry(store, project_root)

    # Git pre-snapshot for rollback (only if not already snapshotted)
    if not issue.get("pre_commit_hash"):
        from tmb.git import ensure_repo, snapshot
        project_root_path = Path(project_root) if not isinstance(project_root, Path) else project_root
        ensure_repo(project_root_path)
        pre_hash = snapshot(project_root_path, f"tmb: snapshot before Issue #{issue_id}")
        if pre_hash:
            store.set_pre_commit_hash(issue_id, pre_hash)

    print(f"[TMB] ⏩ Resuming issue #{issue_id}: {issue['objective']}")
    print(f"[TMB] Project: {project_cfg['name']}  |  Root: {project_root}")

    project_context = None

    def ensure_context() -> str:
        nonlocal project_context
        if project_context is None:
            project_context = _scan_project_context(store, issue_id, goals_md)
        return project_context

    if not store.has_event(issue_id, "discussion_complete"):
        print("[TMB] 💬 Phase: discussion (incomplete)")
        ctx = ensure_context()
        from tmb.nodes.discussion import run_discussion

        run_discussion(goals_md, ctx, store, issue_id)

    tasks = store.get_tasks(issue_id)
    if not tasks:
        print("[TMB] 📋 Phase: planning (pending)")
        ctx = ensure_context()
        discussion_md = store.export_discussion_md(issue_id)

        from tmb.engine import build_graph

        graph = build_graph()
        thread = {"configurable": {"thread_id": f"issue-{issue_id}"}}

        state = graph.invoke(
            {
                "objective": goals_md,
                "project_context": ctx,
                "discussion": discussion_md,
                "issue_id": issue_id,
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
            print(f"[{get_role_name('planner').upper()}] ⚠️ No blueprint was generated.")
            store.close_issue(issue_id, "failed")
            sys.exit(1)

        _show_blueprint(blueprint)

        if not _approve_blueprint(store, issue_id):
            sys.exit(0)

        state = _invoke_with_monitor(graph, None, thread, store, issue_id)
        _finalize_issue(store, issue_id)
        return

    if not store.has_event(issue_id, "blueprint_approved"):
        print("[TMB] ✋ Phase: approval (pending)")
        _show_blueprint(tasks)
        if not _approve_blueprint(store, issue_id):
            sys.exit(0)

    if not store.has_event(issue_id, "execution_plan_generated"):
        print("[TMB] 📝 Phase: execution plan (pending)")
        ctx = ensure_context()
        blueprint = _tasks_to_blueprint(tasks)
        _run_execution_plan(store, issue_id, goals_md, ctx, blueprint)

    actionable = store.get_first_actionable_task(issue_id)
    if not actionable:
        print("[TMB] 🎉 All tasks already completed.")
        store.close_issue(issue_id, "completed")
        store.print_summary(issue_id)
        return

    tasks = store.get_tasks(issue_id)
    blueprint = _tasks_to_blueprint(tasks)
    start_idx = next(
        (i for i, t in enumerate(blueprint) if t["branch_id"] == actionable["branch_id"]),
        0,
    )
    completed_count = sum(1 for t in tasks if t["status"] == "completed")
    total = len(tasks)

    print(
        f"[TMB] 🔧 Phase: execution ([{actionable['branch_id']}] {completed_count}/{total}, "
        f"{completed_count} already done)"
    )
    print("-" * 40)

    discussion_md = store.export_discussion_md(issue_id)
    ctx = ensure_context()
    _run_execution(store, issue_id, goals_md, ctx, discussion_md, blueprint, start_idx)


# ── Prompt Generation ────────────────────────────────────────


_GENERATE_META_PROMPT = """\
You are a prompt engineer for TMB (Trust My Bot), an AI agent framework that \
maximizes project quality through systematic reasoning.

The user is setting up a new project. Here is their description of the project's \
domain and purpose:
---
{purpose}
---

Your task: generate TWO **domain-specialized system prompts** for this project.

1. **Planner prompt** — guides an AI planner that explores the codebase, discusses \
requirements with the human, creates blueprints, and validates execution.
2. **Executor prompt** — guides an AI executor that follows the planner's blueprint \
and executes tasks step by step.

## CRITICAL — Domain-General, Not Task-Specific

The prompts you generate are **persistent system prompts** that will be used for \
EVERY task in this project — not just the first one. They must be domain-specialized \
but task-agnostic.

**DO**:
- Infer the broad domain from the purpose (e.g., "REST API backend in FastAPI" → \
  web development / backend engineering domain)
- Add domain expertise that helps across ALL tasks in that domain (e.g., API design \
  patterns, testing strategies, database conventions)
- Tailor the reasoning examples to the domain, not to one specific task
- Write prompts that work equally well for "add a new endpoint" and "fix a bug" \
  and "refactor the auth layer"

**DO NOT**:
- Reference the specific purpose text as if it's the current task
- Write "The {{role_owner}} wants X" where X is the stated purpose — they will want \
  MANY different things over the project lifetime
- Narrow the Domain Expertise section to only cover the stated purpose
- Generate validation criteria or branch ID examples tied to one specific deliverable

If the purpose reads like a single task (e.g., "build a login page"), generalize it \
to the broader domain (e.g., web application development) before writing the prompts.

---

## Part A — Workflow Framework Contract (MANDATORY — do NOT break or skip)

TMB follows a strict multi-phase workflow. The prompts you generate MUST preserve \
every phase listed below. Removing, merging, or reordering these phases will break \
the framework.

### Planner Prompt — Required Sections (in order)

The generated Planner prompt must contain ALL of the following sections in this order. \
You may ADD domain-specific sections, but you must NEVER remove or skip a required one.

| #  | Section Title                    | Purpose — what it controls in the workflow                  |
|----|----------------------------------|-------------------------------------------------------------|
| 1  | Title + role intro               | Sets the persona. Use {{role_planner}}, {{role_owner}}, {{role_executor}} template vars. |
| 2  | ## Tools                         | Declares available tools: `file_inspect`, `search`, `skill_create`, + `shell` during validation. |
| 3  | ## Systematic Reasoning Process  | NEW section you insert — the 4-phase reasoning rubric (see Part B below). |
| 4  | ## Domain Expertise              | NEW section you insert — domain-specific mental models and vocabulary for this project type. |
| 5  | ## Responsibilities              | The 8-step duty cycle. MUST include ALL of: (1) Explore codebase, (2) Discuss requirements, (3) Identify bugs, (4) Produce Blueprint, (5) Optionally produce Flowchart, (6) Produce Execution Plan, (7) Validate each task, (8) Handle escalations. |
| 6  | ## Validation                    | QA mode: run verification, render verdict as JSON `{{"verdict": "PASS"/"FAIL", "evidence": "...", "failure_details": "..."}}`, provide actionable feedback on FAIL. |
| 7  | ## README Requirement            | Every blueprint's last task writes or updates README.md. |
| 8  | ## Constraints                   | Atomic/idempotent tasks, JSON schema output, bro/ reserved for workflow docs only. |
| 9  | ## Blueprint Schema              | Exact JSON schema: branch_id, description, tools_required, skills_required, success_criteria. |
| 10 | ## Skills                        | Three subsections: Proactive Skill Provisioning, Handling Skill Requests, Skill Assignment. |
| 11 | ## Branch ID Convention          | Hierarchical string IDs: "1", "1.1", "1.1.1". Semantic relationships. |

### Executor Prompt — Required Sections (in order)

| #  | Section Title                    | Purpose                                                     |
|----|----------------------------------|-------------------------------------------------------------|
| 1  | Title + role intro               | Sets the persona. Use {{role_executor}}, {{role_planner}} template vars. |
| 2  | ## Responsibilities              | 4-step cycle: Read task → Execute → Log output → Escalate if blocked. |
| 3  | ## Skills                        | Read Reference Skills before executing. Use `skill_request` for missing skills. Cannot create skills. |
| 4  | ## File Reading Strategy          | file_inspect first, file_read with line ranges, context budget awareness. |
| 5  | ## Constraints                   | Don't question planner, don't skip steps, don't access GOALS/DISCUSSION/BLUEPRINT, bro/ reserved. |
| 6  | ## Output Format                 | Structured JSON log: task_id, status (completed/failed/escalate), actions[], summary, escalation_reason. |

You may ADD domain-specific subsections (e.g., "## SQL Execution Guidelines", \
"## Statistical Testing Patterns") but they go BETWEEN the required sections — \
never replacing them.

---

## Part B — Systematic Reasoning Rubric (insert as section #3 in Planner)

TMB's value proposition is structured thinking that maximizes quality and minimizes \
wasted effort. The Planner prompt you generate MUST embed this reasoning framework \
as a first-class section titled "## Systematic Reasoning Process". Tailor the examples \
to the project domain, but preserve the 4-phase structure:

### Phase 1: Requirement Alignment
Surface and resolve ambiguity BEFORE planning:
- Separate what the {{role_owner}} stated explicitly from what is implied or assumed.
- Rank open questions by impact — resolve high-impact unknowns first.
- Restate the objective in precise, falsifiable terms (e.g., "You want X that \
  satisfies Y, measured by Z") to confirm shared understanding.
- Flag scope risks early: what could balloon, what should be deferred, what is the \
  minimum viable deliverable.

### Phase 2: Solution Exploration
Before committing to a plan, reason through alternatives:
- Generate 2-3 candidate approaches for any non-trivial decision.
- For each approach, evaluate: (a) how it works, (b) strengths, (c) weaknesses, \
  (d) risk profile.
- Select the approach that best balances quality, speed, and maintainability.
- Document the rationale — so the {{role_owner}} can audit the decision and future \
  re-plans start from an informed baseline.

### Phase 3: Quality Maximization
Proactively design for correctness, not just completion:
- Define validation criteria BEFORE execution — what does "done right" look like?
- Identify the highest-risk tasks and front-load them or add extra verification steps.
- Anticipate failure modes at each step. Add guardrails or fallback paths where the \
  cost of failure is high.
- Apply domain-specific quality checks appropriate to this project type.

### Phase 4: Efficiency Optimization
Minimize time and token cost without sacrificing quality:
- Order tasks to maximize information gain early (e.g., profile data before queries, \
  read configs before designing architecture).
- Identify parallelizable work and batch where possible.
- Prefer simple approaches that meet success criteria over over-engineered solutions.
- Reuse existing code, patterns, and skills instead of building from scratch.

---

## Part C — Style Reference

Use the tone and structure of the `software-engineering` sample below as your STYLE reference. \
Notice how it assigns a concrete professional persona, uses direct language, and gives \
the executor clear boundaries. Apply this same professional, opinionated tone — but \
with the FULL feature set from the base prompts (validation, skill provisioning, \
skill_request, SQLite execution plans).

<style_reference_planner>
{style_reference_planner}
</style_reference_planner>

<style_reference_executor>
{style_reference_executor}
</style_reference_executor>

---

## Part D — Base Prompts (canonical feature set)

These are the CANONICAL base prompts with the complete TMB feature set. Your generated \
prompts must include every feature present here. Do NOT downgrade to the simpler \
software-engineering version — the base prompts are the source of truth for what the framework \
supports.

<base_planner>
{base_planner}
</base_planner>

<base_executor>
{base_executor}
</base_executor>

---

## Part E — Domain Examples

Study how these domain-specialized samples add expertise sections, specific constraints, \
and tailored blueprint examples. Apply the same pattern to the user's project purpose.

{few_shot_examples}

---

## Output Format

Return EXACTLY two markdown documents separated by this delimiter on its own line:
===PROMPT_SEPARATOR===

First document: the Planner prompt (with ALL required sections from Part A + the \
Systematic Reasoning Process from Part B + Domain Expertise tailored to the DOMAIN).
Second document: the Executor prompt (with ALL required sections from Part A).

Both must use {{role_planner}}, {{role_executor}}, and {{role_owner}} template variables \
(NOT hardcoded role names). Keep the bro/ reserved directory rule.

FINAL CHECK before returning: re-read both prompts and verify they would work \
equally well for ANY task in this domain — not just the stated purpose. If the \
role intro says "The {{role_owner}} wants to [specific thing]", rewrite it to \
describe the domain instead.
"""


_PRESET_KEYWORDS: dict[str, list[str]] = {
    "software-engineering": [
        "api", "backend", "frontend", "web", "app", "microservice", "rest",
        "graphql", "react", "vue", "angular", "fastapi", "django", "flask",
        "express", "node", "typescript", "javascript", "rust", "go", "java",
        "kubernetes", "docker", "ci/cd", "devops", "architecture", "saas",
        "mobile", "ios", "android", "crud", "auth", "deploy", "infra",
        "monorepo", "cli", "sdk", "library", "framework", "testing",
    ],
    "data-analytics": [
        "sql", "data", "analytics", "etl", "pipeline", "csv", "parquet",
        "duckdb", "bigquery", "snowflake", "redshift", "a/b test",
        "ab test", "experiment", "statistics", "dashboard", "report",
        "visualization", "tableau", "looker", "metabase", "pandas",
        "polars", "spark", "airflow", "dbt", "warehouse", "lake",
        "metric", "kpi", "forecast", "ml", "model", "training",
        "feature engineering", "embedding", "recommendation", "matching",
    ],
}

_PRESET_ROLES: dict[str, dict[str, str]] = {
    "software-engineering": {
        "owner": "Chief Architect",
        "planner": "Architect",
        "executor": "SWE",
    },
    "data-analytics": {
        "owner": "Lead Analyst",
        "planner": "Analytics Architect",
        "executor": "Data Engineer",
    },
}


def _quick_project_snapshot(project_root: Path) -> dict[str, str]:
    """Lightweight project scan for setup — no Store needed.

    Returns a dict with 'tech_stack', 'key_docs', and 'is_empty' fields.
    """
    root = project_root.resolve()

    # Check if the project has meaningful content beyond TMB scaffolding
    _ignore_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tmb", "bro", "TMB"}
    _tmb_scaffolded = {"pyproject.toml", "uv.lock", ".python-version"}
    has_files = False
    if root.exists():
        for f in root.iterdir():
            if f.name.startswith(".") or f.name in _ignore_dirs:
                continue
            if f.is_file() and f.name not in _tmb_scaffolded:
                has_files = True
                break
            if f.is_dir():
                # Any non-hidden file one level down counts
                if any(c.is_file() for c in f.iterdir() if not c.name.startswith(".")):
                    has_files = True
                    break

    tech_stack = detect_tech_stack(root) if has_files else "unknown"
    key_docs = read_key_docs(root) if has_files else ""

    return {
        "tech_stack": tech_stack,
        "key_docs": key_docs[:6000],  # cap for prompt budget
        "is_empty": str(not has_files),
    }


def _detect_preset(purpose: str, snapshot: dict[str, str] | None = None) -> str:
    """Classify a project into the closest sample preset.

    Uses keyword overlap scoring from both the user's purpose description
    AND the project snapshot (tech stack, key files) when available.
    Returns "software-engineering", "data-analytics", or "generic".
    """
    # Combine purpose + project signals into one string for matching
    signals = purpose.lower()
    if snapshot:
        signals += " " + snapshot.get("tech_stack", "").lower()
        signals += " " + snapshot.get("key_docs", "").lower()

    scores: dict[str, int] = {}
    for preset, keywords in _PRESET_KEYWORDS.items():
        scores[preset] = sum(1 for kw in keywords if kw in signals)

    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best] == 0:
        return "generic"
    return best


def _copy_sample_prompts(preset: str) -> bool:
    """Copy a sample preset's prompts to the user prompts dir.

    Returns True if prompts were copied, False if preset is generic or files missing.
    """
    sample_dir = SAMPLES_DIR / preset
    if not sample_dir.exists():
        return False

    out_dir = user_prompts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    copied = False
    for name in ("planner.md", "executor.md"):
        src = sample_dir / name
        if src.exists():
            (out_dir / name).write_text(src.read_text())
            copied = True

    return copied


def _generate_prompts(
    purpose: str,
    preset: str = "software-engineering",
    snapshot: dict[str, str] | None = None,
) -> bool:
    """Use the LLM to generate tailored planner & executor prompts.

    The detected *preset* is used as the primary style reference.
    When *snapshot* is provided (tech stack, key docs), it's injected
    into the meta-prompt so the LLM can tailor prompts to the actual codebase.
    Returns True if prompts were generated successfully, False otherwise.
    """
    import sys

    try:
        from tmb.config import get_llm
    except Exception:
        return False

    # Load base templates (canonical feature set) from system/
    base_planner_path = SYSTEM_PROMPTS_DIR / "planner.md"
    base_executor_path = SYSTEM_PROMPTS_DIR / "executor.md"
    if not base_planner_path.exists() or not base_executor_path.exists():
        return False

    base_planner = base_planner_path.read_text()
    base_executor = base_executor_path.read_text()

    # Use detected preset as the primary style reference
    style_dir = SAMPLES_DIR / preset
    if not style_dir.exists():
        # Fallback to software-engineering if detected preset dir missing
        style_dir = SAMPLES_DIR / "software-engineering"
    style_planner = (style_dir / "planner.md").read_text() if (style_dir / "planner.md").exists() else ""
    style_executor = (style_dir / "executor.md").read_text() if (style_dir / "executor.md").exists() else ""

    # Load remaining samples as few-shot examples (exclude the style reference)
    samples_dir = SAMPLES_DIR
    few_shot_parts = []
    if samples_dir.exists():
        for sample_dir in sorted(samples_dir.iterdir()):
            if not sample_dir.is_dir() or sample_dir.name == style_dir.name:
                continue
            planner_path = sample_dir / "planner.md"
            executor_path = sample_dir / "executor.md"
            if planner_path.exists():
                few_shot_parts.append(
                    f"### Example: {sample_dir.name}\n\n"
                    f"<example_planner>\n{planner_path.read_text()}\n</example_planner>"
                )
            if executor_path.exists():
                few_shot_parts.append(
                    f"<example_executor>\n{executor_path.read_text()}\n</example_executor>"
                )

    few_shot_examples = "\n\n".join(few_shot_parts) if few_shot_parts else "(no examples available)"

    # Build project context addendum from snapshot
    project_context = ""
    if snapshot and snapshot.get("is_empty") != "True":
        ctx_parts = []
        if snapshot.get("tech_stack") and snapshot["tech_stack"] != "unknown":
            ctx_parts.append(f"**Detected tech stack**: {snapshot['tech_stack']}")
        if snapshot.get("key_docs"):
            ctx_parts.append(f"**Key project files**:\n{snapshot['key_docs']}")
        if ctx_parts:
            project_context = (
                "\n\nThe project already has an existing codebase. "
                "Use this context to tailor domain expertise, tooling references, "
                "and quality checks to the actual stack:\n\n"
                + "\n\n".join(ctx_parts)
            )

    meta_prompt = _GENERATE_META_PROMPT.format(
        purpose=purpose + project_context,
        base_planner=base_planner,
        base_executor=base_executor,
        style_reference_planner=style_planner,
        style_reference_executor=style_executor,
        few_shot_examples=few_shot_examples,
    )

    # Call LLM
    try:
        llm = get_llm("planner")
        print("    Generating tailored prompts", end="", flush=True)

        response = llm.invoke(meta_prompt)
        content = response.content
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        print(" done. 🧠")
    except Exception as e:
        print(f"\n    [warn] Prompt generation failed: {e}")
        return False

    # Parse output — expect two documents separated by ===PROMPT_SEPARATOR===
    separator = "===PROMPT_SEPARATOR==="
    if separator not in content:
        print("    [warn] LLM output missing separator — falling back to defaults.")
        return False

    parts = content.split(separator, 1)
    planner_text = parts[0].strip()
    executor_text = parts[1].strip()

    if len(planner_text) < 200 or len(executor_text) < 200:
        print("    [warn] Generated prompts too short — falling back to defaults.")
        return False

    # Write to user prompts dir
    out_dir = user_prompts_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "planner.md").write_text(planner_text)
    (out_dir / "executor.md").write_text(executor_text)

    print(f"    Custom planner prompt → .tmb/prompts/planner.md ✅")
    print(f"    Custom executor prompt → .tmb/prompts/executor.md ✅")
    return True


def _inject_tmb_dependency(toml_path: Path, content: str, tmb_rel: Path | None) -> None:
    """Add TMB as a dependency to an existing pyproject.toml without overwriting.

    Handles three cases:
      1. [project] with dependencies list → append the dependency to the list
      2. [project] without dependencies    → add dependencies key
      3. No [project] section              → append a minimal block

    When tmb_rel is a Path (local/editable install), uses "tmb" as the dependency name
    and adds [tool.uv.sources] with the path entry.
    When tmb_rel is None (PyPI install), uses "trustmybot" as the dependency name
    and skips [tool.uv] / [tool.uv.sources] entirely.
    """
    import re as _re

    dep_name = "tmb" if tmb_rel is not None else "trustmybot"

    lines = content.splitlines(keepends=True)
    modified = False

    # ── Case 1 & 2: [project] section exists ──
    dep_pattern = _re.compile(r'^dependencies\s*=\s*\[')
    project_header = _re.compile(r'^\[project\]')

    in_project = False
    in_deps = False
    insert_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if project_header.match(stripped):
            in_project = True
            insert_idx = i + 1  # fallback: right after [project]
            continue
        if in_project and stripped.startswith("[") and not stripped.startswith("[project"):
            # Left [project] section without finding deps
            break
        if in_project and dep_pattern.match(stripped):
            in_deps = True
            # Single-line form: dependencies = []
            if "]" in stripped:
                if "[]" in stripped:
                    lines[i] = line.replace("[]", f'[\n    "{dep_name}",\n]')
                else:
                    lines[i] = line.replace("]", f'    "{dep_name}",\n]')
                modified = True
                break
            continue
        if in_deps:
            if "]" in stripped:
                # Insert before the closing bracket
                lines.insert(i, f'    "{dep_name}",\n')
                modified = True
                break

    if not modified and in_project and insert_idx is not None:
        # [project] exists but no dependencies key — add it
        lines.insert(insert_idx, f'dependencies = [\n    "{dep_name}",\n]\n')
        modified = True

    if not modified:
        # No [project] at all — append a minimal block
        lines.append(f'\n[project]\ndependencies = [\n    "{dep_name}",\n]\n')

    joined = "".join(lines)

    # ── Add [tool.uv.sources] if local install ──
    if tmb_rel is not None:
        if "[tool.uv.sources]" not in joined:
            uv_section = ""
            if "[tool.uv]" not in joined:
                uv_section = "\n[tool.uv]\npackage = false\n"
            joined = (
                joined.rstrip("\n") + "\n"
                + uv_section
                + f'\n[tool.uv.sources]\ntmb = {{ path = "./{tmb_rel}", editable = true }}\n'
            )
        elif "tmb" not in joined.split("[tool.uv.sources]")[1].split("[")[0]:
            # [tool.uv.sources] exists but no tmb entry
            joined = joined.replace(
                "[tool.uv.sources]\n",
                f'[tool.uv.sources]\ntmb = {{ path = "./{tmb_rel}", editable = true }}\n',
            )

    toml_path.write_text(joined)
    print(f"    Added TMB dependency to {toml_path}")
    print(f"    Run `uv sync` to install.")


# ── Local model setup helpers ─────────────────────────────────────────────


def _verify_ollama_model(base_url: str, model_name: str) -> bool:
    """Verify an Ollama model exists and responds. Quick ping with tiny prompt."""
    import urllib.request
    import urllib.error

    print(f"    Verifying {model_name}...")
    try:
        payload = json.dumps({"model": model_name, "prompt": "hi", "stream": False}).encode()
        req = urllib.request.Request(
            f"{base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
            if "error" in data:
                print(f"    ❌ Model error: {data['error']}")
                return False
            print(f"    ✅ {model_name} is working.")
            return True
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode())
            print(f"    ❌ {body.get('error', f'HTTP {e.code}')}")
        except Exception:
            print(f"    ❌ Ollama returned HTTP {e.code}")
        return False
    except (urllib.error.URLError, ConnectionError, OSError):
        print(f"    ❌ Can't reach Ollama at {base_url}")
        return False
    except Exception as e:
        print(f"    ❌ Verification failed: {e}")
        return False


def _pick_ollama_model() -> str:
    """Show recommended model menu and return the chosen model name."""
    print("    Recommended models:")
    print("      1) llama3.1:8b        (default — good all-rounder)")
    print("      2) deepseek-r1:7b     (reasoning focused)")
    print("      3) qwen3:8b           (open-source, multilingual)")
    print("      4) Enter custom name")
    choice = input("    Choice [1]: ").strip() or "1"
    _options = {"1": "llama3.1:8b", "2": "deepseek-r1:7b", "3": "qwen3:8b"}
    if choice == "4":
        return input("    Model name: ").strip() or "llama3.1:8b"
    return _options.get(choice, "llama3.1:8b")


def _ollama_pull(model_name: str):
    """Pull an Ollama model with live output."""
    print(f"    Pulling {model_name}... (this may take a few minutes)")
    try:
        proc = subprocess.run(
            ["ollama", "pull", model_name],
            timeout=600,  # 10 min for large models
        )
        if proc.returncode == 0:
            print(f"    ✅ {model_name} ready.")
        else:
            print(f"    ⚠️  Pull failed. Try manually: ollama pull {model_name}")
    except FileNotFoundError:
        print(f"    ⚠️  'ollama' command not found. Install: https://ollama.ai")
    except subprocess.TimeoutExpired:
        print(f"    ⚠️  Pull timed out. Try manually: ollama pull {model_name}")


def _setup_ollama(env_path) -> "tuple[str, str, str, str | None] | None":
    """Ollama-specific setup: scan, list models, auto-pull if needed."""
    import urllib.request
    import urllib.error

    base_url = "http://localhost:11434"
    extra_pkg = "tmb[ollama]"

    # Show GPU detection
    from tmb.config import _detect_gpu_layers
    import platform
    gpu_layers = _detect_gpu_layers()
    if gpu_layers > 0:
        if platform.system() == "Darwin":
            print("    GPU: Apple Silicon (MPS) detected — GPU acceleration enabled")
        else:
            print("    GPU: NVIDIA GPU detected — CUDA acceleration enabled")
    else:
        print("    GPU: No GPU detected — running on CPU")
    print()

    # Try to connect to Ollama
    try:
        req = urllib.request.Request(f"{base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            models = [m["name"] for m in data.get("models", [])]
    except (urllib.error.URLError, ConnectionError, OSError):
        # Ollama not running — check if installed
        import shutil
        if shutil.which("ollama"):
            print("    ⚠️  Ollama is installed but not running.")
            print("    Start it with: ollama serve")
        else:
            print("    ⚠️  Ollama not found.")
            print("    Install it: https://ollama.ai")
            print("    Then: ollama serve")

        # Offer to pull a model
        print()
        model_name = _pick_ollama_model()
        _ollama_pull(model_name)
        return ("ollama", model_name, base_url, extra_pkg)

    if not models:
        print("    Ollama is running but has no models.")
        while True:
            print()
            model_name = _pick_ollama_model()
            _ollama_pull(model_name)
            if _verify_ollama_model(base_url, model_name):
                return ("ollama", model_name, base_url, extra_pkg)
            print("    Model verification failed. Let's try another.")

    # Show available models
    print()
    print("    Available models:")
    for i, m in enumerate(models, 1):
        print(f"      {i}) {m}")
    print(f"      p) Pull a new model")
    model_choice = input(f"    Pick a model [1]: ").strip() or "1"

    if model_choice.lower() == "p":
        while True:
            print()
            model_name = _pick_ollama_model()
            _ollama_pull(model_name)
            if _verify_ollama_model(base_url, model_name):
                return ("ollama", model_name, base_url, extra_pkg)
            print("    Model verification failed. Let's try another.")

    try:
        idx = int(model_choice) - 1
        selected_model = models[idx]
    except (ValueError, IndexError):
        selected_model = models[0]

    if _verify_ollama_model(base_url, selected_model):
        return ("ollama", selected_model, base_url, extra_pkg)

    # Existing model failed verification — let user pick another
    print("    Model verification failed. Let's try another.")
    while True:
        print()
        model_name = _pick_ollama_model()
        _ollama_pull(model_name)
        if _verify_ollama_model(base_url, model_name):
            return ("ollama", model_name, base_url, extra_pkg)
        print("    Model verification failed. Let's try another.")


def _setup_local_model(env_path) -> "tuple[str, str, str, str | None] | None":
    """Interactive local model setup — scan for Ollama, LM Studio, or custom endpoint.

    Returns (provider, model_name, base_url, extra_pkg) or None if skipped.
    """
    import urllib.request
    import urllib.error

    _LOCAL_PLATFORMS = [
        ("1", "Ollama",    "http://localhost:11434"),
        ("2", "LM Studio", "http://localhost:1234/v1"),
        ("3", "Other / Custom (OpenAI-compatible)", None),
    ]

    print()
    print("  Which local platform?")
    for key, label, _ in _LOCAL_PLATFORMS:
        print(f"    {key}) {label}")
    platform_choice = input("  Choice [1]: ").strip() or "1"
    platform = next((p for p in _LOCAL_PLATFORMS if p[0] == platform_choice), _LOCAL_PLATFORMS[0])
    _, platform_name, default_url = platform

    if platform_name == "Ollama":
        return _setup_ollama(env_path)
    else:
        # LM Studio or Custom — OpenAI-compatible endpoint
        if default_url:
            url = input(f"    Base URL [{default_url}]: ").strip() or default_url
        else:
            url = input("    Base URL (e.g. http://localhost:8080/v1): ").strip()
            if not url:
                print("    No URL entered — skipping.")
                return None

        model_name = input("    Model name: ").strip()
        if not model_name:
            print("    No model name — skipping.")
            return None

        # OpenAI-compatible endpoints need OPENAI_API_KEY set (even if unused)
        existing_env = env_path.read_text() if env_path.exists() else ""
        if "OPENAI_API_KEY" not in existing_env:
            with open(env_path, "a") as f:
                f.write("OPENAI_API_KEY=not-needed\n")

        print(f"    ✅ Configured: {platform_name} at {url} with model {model_name}")
        return ("openai", model_name, url, None)


# ── CLI Commands ─────────────────────────────────────────────


def setup():
    """Interactive setup — writes .tmb/config/project.yaml and .env."""
    from pathlib import Path

    print()
    print("  🤙  T R U S T   M E   B R O  🤙")
    print("  ─────────────────────────────────")
    print("  Yo, let's get this project set up.")
    print()

    ensure_dirs()
    project_root = get_project_root()
    detected_name = project_root.name

    name = input(f"  What's this project called? [{detected_name}]: ").strip() or detected_name

    # Write minimal project.yaml EARLY as a sentinel for _is_first_run().
    # Full config (roles, purpose) is written later and overwrites this.
    _early_cfg_path = user_cfg_dir() / "project.yaml"
    _early_cfg_path.parent.mkdir(parents=True, exist_ok=True)
    if not _early_cfg_path.exists():
        with open(_early_cfg_path, "w") as f:
            yaml.dump({"name": name}, f, default_flow_style=False, sort_keys=False)

    _needs_restart = False

    # ── LLM Provider (moved before purpose — needed for prompt generation) ──
    _PROVIDER_MENU = [
        ("1", "Anthropic (Claude)",  "ANTHROPIC_API_KEY", "anthropic",    None),
        ("2", "OpenAI (GPT)",        "OPENAI_API_KEY",    "openai",       None),
        ("3", "Google (Gemini)",     "GOOGLE_API_KEY",    "google",       "tmb[google]"),
        ("4", "Groq",               "GROQ_API_KEY",      "groq",         "tmb[groq]"),
        ("5", "Mistral",            "MISTRAL_API_KEY",   "mistral",      "tmb[mistral]"),
        ("6", "DeepSeek",           "DEEPSEEK_API_KEY",  "deepseek",     "tmb[deepseek]"),
        ("7", "Claude Code",        None,                "claude_code",  None),
        ("8", "Local model",        None,                "local",        None),
        ("s", "Skip for now bro",   None,                None,           None),
    ]

    _PROVIDER_DEFAULTS = {
        "anthropic":   {"name": "claude-sonnet-4-6", "temperature": 0.3},
        "openai":      {"name": "gpt-4o", "temperature": 0.3},
        "google":      {"name": "gemini-2.0-flash", "temperature": 0.3},
        "groq":        {"name": "llama-3.3-70b-versatile", "temperature": 0.3},
        "mistral":     {"name": "mistral-large-latest", "temperature": 0.3},
        "deepseek":    {"name": "deepseek-chat", "temperature": 0.3},
        "claude_code": {"name": "sonnet", "temperature": 0},
        "ollama":      {"name": "llama3.1:8b", "temperature": 0.3, "base_url": "http://localhost:11434"},
    }

    env_path = project_root / ".env"
    llm_configured = env_path.exists()
    if llm_configured:
        print(f"  .env already exists — nice, brain's already wired up. 🧠")
    else:
        print()
        print("  Which LLM is gonna be your bro's brain?")
        for key, label, _, _, _ in _PROVIDER_MENU:
            print(f"    {key}) {label}")
        choice = input("  Choice [1]: ").strip() or "1"

        selected = next((m for m in _PROVIDER_MENU if m[0] == choice), None)
        model_name_override = None
        base_url_override = None
        env_lines = []
        if selected and selected[0] != "s":
            _, label, env_var, provider_name, extra_pkg = selected

            if provider_name == "local":
                # Local model sub-menu
                local_result = _setup_local_model(env_path)
                if local_result:
                    provider_name, model_name_override, base_url_override, extra_pkg = local_result
                    llm_configured = True  # local models don't need API keys
                else:
                    provider_name = None  # skipped
            elif provider_name == "claude_code":
                import shutil
                if shutil.which("claude"):
                    print("    Claude Code detected. No API key needed.")
                    llm_configured = True
                else:
                    print("    Claude Code CLI not found.")
                    print("    Install it: https://docs.anthropic.com/en/docs/claude-code")
                    print("    After installing, re-run: bro setup")
                    provider_name = None  # Skip config writing
            else:
                # Cloud provider — existing flow
                if env_var:
                    api_key = input(f"    {env_var}: ").strip()
                    if api_key:
                        env_lines.append(f"{env_var}={api_key}")
                        llm_configured = True

            if extra_pkg:
                _is_tool_install = not TMB_ROOT.resolve().is_relative_to(project_root.resolve())
                if _is_tool_install:
                    # Auto-install the provider package into the tool environment
                    pip_pkg = extra_pkg.split("[")[1].rstrip("]")  # "tmb[ollama]" → "ollama"
                    lang_pkg = f"langchain-{pip_pkg}"
                    print(f"    Installing {lang_pkg}...")
                    channel = _detect_install_channel()
                    if channel == "dev":
                        from_src = "git+https://github.com/ZaxShen/TMB@dev"
                    else:
                        from_src = "trustmybot"

                    _pkg_installed = False
                    try:
                        result = subprocess.run(
                            ["uv", "tool", "install", "--upgrade", "--reinstall",
                             "--from", from_src, "trustmybot",
                             "--with", lang_pkg],
                            capture_output=True, text=True, timeout=180,
                        )
                        if result.returncode == 0:
                            _pkg_installed = True
                    except Exception:
                        pass

                    if not _pkg_installed:
                        # Try uv pip install as a second option
                        try:
                            result = subprocess.run(
                                ["uv", "pip", "install", "--python", sys.executable, lang_pkg],
                                capture_output=True, text=True, timeout=120,
                            )
                            if result.returncode == 0:
                                _pkg_installed = True
                        except Exception:
                            pass

                    if _pkg_installed:
                        print(f"    ✅ {lang_pkg} installed.")
                        # The tool venv was reinstalled — the current process can't use it.
                        # Finish writing config, then tell user to re-run.
                        _needs_restart = True
                    else:
                        print(f"    ⚠️  Couldn't auto-install {lang_pkg}.")
                        print(f"    Install manually, then re-run bro:")
                        print(f"      uv tool install --with {lang_pkg} trustmybot")
                        _needs_restart = True  # Can't continue without the package
                else:
                    print(f"    Heads up — install the provider:  uv add {extra_pkg}")

        if env_lines:
            env_path.write_text("\n".join(env_lines) + "\n")
            print(f"    Wrote {env_path} — brain connected. 🔌")
            # Reload .env so get_llm() can find the key
            from dotenv import load_dotenv
            load_dotenv(env_path, override=True)
        elif choice != "s":
            print("    No API key entered — set it in .env before running, bro.")

        # Write nodes.yaml with the selected provider
        if selected and selected[0] != "s" and provider_name:
            if provider_name in _PROVIDER_DEFAULTS or (model_name_override and base_url_override):
                defaults = _PROVIDER_DEFAULTS.get(provider_name, {})
                model_name = model_name_override or defaults.get("name", "")
                base_url = base_url_override or defaults.get("base_url")
                planner_model = {"provider": provider_name, "name": model_name, "temperature": 0.3}
                executor_model = {"provider": provider_name, "name": model_name, "temperature": 0}
                evolve_model = {"provider": provider_name, "name": model_name, "temperature": 0.3}
                if base_url:
                    planner_model["base_url"] = base_url
                    executor_model["base_url"] = base_url
                    evolve_model["base_url"] = base_url
                nodes_cfg = {
                    "planner": {
                        "model": planner_model,
                        "tools": ["file_inspect", "search", "web_search", "skill_create"],
                    },
                    "executor": {
                        "model": executor_model,
                        "tools": ["shell", "file_read", "file_write", "search", "skill_request"],
                    },
                    "evolve": {
                        "model": evolve_model,
                        "tools": ["file_read", "file_write", "search", "shell"],
                    },
                }
                # Claude Code uses its own tools — don't bind TMB tools
                if provider_name == "claude_code":
                    nodes_cfg["planner"]["tools"] = []
                    nodes_cfg["executor"]["tools"] = []
                    nodes_cfg["evolve"]["tools"] = []
                nodes_path = user_cfg_dir() / "nodes.yaml"
                nodes_path.parent.mkdir(parents=True, exist_ok=True)
                with open(nodes_path, "w") as f:
                    yaml.dump(nodes_cfg, f, default_flow_style=False, sort_keys=False)
                print(f"    Saved LLM config → .tmb/config/nodes.yaml")

    # ── Project Snapshot ──
    snapshot = _quick_project_snapshot(project_root)
    if snapshot["is_empty"] == "False":
        print()
        tech = snapshot.get("tech_stack", "unknown")
        if tech != "unknown":
            print(f"  📂 Existing project detected — stack: {tech}")
        else:
            print(f"  📂 Existing project detected")

    # ── Project Purpose & Auto-Tuned Prompts ──
    print()
    print("  Tell me what this project's about so I can auto-tune prompts for you.")
    print("    Examples: 'A/B test analysis for matchmaking experiments'")
    print("              'ETL pipeline for cleaning CSV sales data with DuckDB'")
    print("              'REST API backend in FastAPI with PostgreSQL'")
    purpose = input("  Project purpose (Enter to skip): ").strip()

    # Nudge user if purpose looks like a single task, not a domain description
    if purpose:
        _task_verbs = ["build ", "create ", "fix ", "add ", "make ", "write ", "show ", "tell ",
                       "update ", "deploy ", "set up ", "implement ", "design "]
        looks_like_task = any(purpose.lower().startswith(v) for v in _task_verbs)
        if looks_like_task:
            print("    💡 Tip: describe the project DOMAIN, not a single task.")
            print("       e.g., 'FastAPI backend with PostgreSQL' instead of 'build a REST API'")
            redo = input("    Rephrase? (Enter to keep, or type new purpose): ").strip()
            if redo:
                purpose = redo

    # Auto-detect the closest sample preset from description + project context
    detected_preset = _detect_preset(purpose or "", snapshot) if (purpose or snapshot["is_empty"] == "False") else "generic"
    roles_cfg: dict = {}
    if detected_preset != "generic":
        roles_cfg = {"preset": detected_preset, **_PRESET_ROLES[detected_preset]}
        print(f"    Detected domain: {detected_preset} 🎯")
    elif purpose:
        print("    Domain: generic (no strong match — using defaults)")

    config = {
        "name": name,
        "max_retry_per_task": 3,
    }
    if roles_cfg:
        config["roles"] = roles_cfg
    if purpose:
        config["purpose"] = purpose

    # Write config early so _generate_prompts can load it
    config_path = user_cfg_dir() / "project.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"    Saved config → {config_path}")

    # Generate or copy tailored prompts based on detected preset + project snapshot
    prompt_source = purpose or (snapshot["is_empty"] == "False")
    if prompt_source and llm_configured:
        print()
        print("  === Cooking up custom prompts... 🧪 ===")
        generated = _generate_prompts(purpose or name, preset=detected_preset, snapshot=snapshot)
        if not generated:
            # LLM generation failed — fall back to copying the sample
            if _copy_sample_prompts(detected_preset):
                print(f"    Used {detected_preset} sample as base — still solid. 📋")
            else:
                print("    No worries, using defaults. Re-run `tmb setup` anytime to retry.")
    elif prompt_source:
        # No LLM available — copy the matched sample directly
        if _copy_sample_prompts(detected_preset):
            print(f"    Copied {detected_preset} prompts → .tmb/prompts/ 📋")
            print("    Hook up an API key and re-run `tmb setup` for fully custom ones.")

    goals_path = docs_dir() / "GOALS.md"
    if not goals_path.exists():
        goals_path.parent.mkdir(parents=True, exist_ok=True)
        goals_path.write_text(
            "# Goals\n\n"
            "Write your goals below, bro. Your Planner will read this and chat with you about it.\n\n"
            "---\n\n"
        )
        print(f"    Created {goals_path}")

    # ── Web Search ────────────────────────────────────────────
    print()
    print("  === Web Search ===")
    print()
    print("    Your bro can Google stuff while planning.")
    print("    Tavily (tavily.com) gives the best results — free tier: 1K searches/month.")
    print("    Without a key, DuckDuckGo is used as fallback. Still works, just less sharp.")
    print()
    tavily_key = input("    TAVILY_API_KEY (Enter to skip): ").strip()
    if tavily_key:
        existing_env = env_path.read_text() if env_path.exists() else ""
        if "TAVILY_API_KEY" not in existing_env:
            with open(env_path, "a") as f:
                f.write(f"\nTAVILY_API_KEY={tavily_key}\n")
            print("    Added Tavily key to .env — search game strong. 🔍")
    else:
        print("    Skipped — DuckDuckGo fallback it is.")

    # ── Project-level pyproject.toml (dev installs only) ─────
    is_local_install = TMB_ROOT.resolve().is_relative_to(project_root.resolve())

    if is_local_install:
        project_toml = project_root / "pyproject.toml"
        tmb_rel = TMB_ROOT.resolve().relative_to(project_root.resolve())

        if not project_toml.exists():
            print()
            print("  No pyproject.toml found at project root.")
            create = input("    Create one with TMB as a dependency? (yes/no) [yes]: ").strip().lower()
            if create in ("", "yes", "y"):
                toml_content = (
                    f'[project]\nname = "{name}"\nversion = "0.1.0"\n'
                    f'requires-python = ">=3.13"\n'
                    f'dependencies = [\n'
                    f'    "tmb",\n'
                    f']\n\n'
                    f'[tool.uv]\npackage = false\n\n'
                    f'[tool.uv.sources]\ntmb = {{ path = "./{tmb_rel}", editable = true }}\n'
                )
                project_toml.write_text(toml_content)
                print(f"    Wrote {project_toml}")
                print(f"    Run `uv sync` to install.")
        else:
            existing = project_toml.read_text()
            if '"tmb"' not in existing and "'tmb'" not in existing:
                print()
                print("  Found existing pyproject.toml — your project is already set up. 👍")
                print("  TMB is not listed as a dependency yet.")
                inject = input("    Add TMB as a path dependency? (yes/no) [yes]: ").strip().lower()
                if inject in ("", "yes", "y"):
                    _inject_tmb_dependency(project_toml, existing, tmb_rel)
            else:
                print()
                print("  Found existing pyproject.toml with TMB already wired up. 👍")

    dd = docs_dir().name
    print()
    print("  ─────────────────────────────────")
    print("  🤙 Setup complete, bro!")
    print()
    print(f"  Next steps:")
    print(f"    1. Write your goals in {dd}/GOALS.md")
    if is_local_install:
        print(f"    2. Run: uv run tmb")
    else:
        print(f"    2. Run: bro")
    print()
    print(f"  Need Notion, GitHub, Slack, or any other integration?")
    print(f"    No problem — Trust Me Bro, I'll set it up when you need it. 🫡")
    if is_local_install:
        print(f"    (or configure manually: TMB/ARCHITECTURE.md § MCP Integration)")
    print()
    print(f"  Advanced settings (retries, roles, prompts, paths):")
    if is_local_install:
        print(f"    → TMB/ARCHITECTURE.md § Configuration")
    else:
        print(f"    → https://github.com/ZanMax/TMB")
    print()

    if _needs_restart:
        print()
        print("  🔄 Please run `bro` again to start working.")
        print("     (The provider package was installed into a fresh environment.)")
        print()
        sys.exit(0)


def _is_first_run() -> bool:
    """Detect whether setup has ever been run for this project."""
    cfg = user_cfg_dir()
    # Check multiple indicators — if ANY config file exists, setup has run
    return not (cfg / "project.yaml").exists() and not (cfg / "nodes.yaml").exists()


def scan():
    """Scan the project directory and populate TMB's DB with file registry + context."""
    from tmb.scanner import scan_project

    ensure_dirs()
    store = Store()
    project_root = get_project_root()

    print(f"[TMB] 🔍 Scanning project: {project_root}")
    print("-" * 40)

    stats = scan_project(project_root, store)

    print(f"[TMB] ✅ Scan complete:")
    print(f"  Files registered: {stats['file_count']}")
    print(f"  Total size: {_human_bytes(stats['total_size'])}")
    print(f"  Tech stack: {stats['tech_stack']}")
    if stats["has_git"]:
        print(f"  Git history: captured")
    print()
    print("[TMB] Context stored in DB — the planner will use this automatically.")


def _human_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def _detect_install_channel() -> str:
    """Detect whether TMB was installed from PyPI (stable) or git (dev).

    Reads PEP 610 direct_url.json from the installed distribution:
      - Git URL containing '@dev' → "dev"
      - Anything else (PyPI, editable, unknown) → "stable"
    """
    import importlib.metadata

    try:
        dist = importlib.metadata.distribution("trustmybot")
        raw = dist.read_text("direct_url.json")
        if raw:
            info = json.loads(raw)
            url = info.get("url", "")
            vcs = info.get("vcs_info", {})
            if "github.com" in url and vcs.get("requested_revision") == "dev":
                return "dev"
    except Exception:
        pass
    return "stable"


def upgrade():
    """Upgrade TMB to the latest version, respecting install channel."""
    import importlib.metadata

    # Show current version
    try:
        current = importlib.metadata.version("trustmybot")
    except importlib.metadata.PackageNotFoundError:
        current = "unknown"

    channel = _detect_install_channel()

    print()
    print(f"  🤙 Trust Me Bro ({channel})")
    print(f"     Current version: {current}")
    print()

    # Dev channel: self-upgrade from git
    if channel == "dev":
        print("  Upgrading from dev branch...")
        print()
        try:
            result = subprocess.run(
                ["uv", "tool", "install", "--upgrade", "--reinstall",
                 "--from", "git+https://github.com/ZaxShen/TMB@dev",
                 "trustmybot"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode == 0:
                # Get the new version from a fresh process (our importlib cache is stale)
                new_ver = subprocess.run(
                    ["bro", "--version"],
                    capture_output=True, text=True, timeout=10,
                )
                new_version = new_ver.stdout.strip() if new_ver.returncode == 0 else None
                if new_version:
                    print(f"  ✅ {new_version}")
                else:
                    print("  ✅ Upgrade complete.")
                if current != "unknown" and new_version and current in new_version:
                    print(f"     (already on latest)")
            else:
                print(f"  ⚠️  Upgrade failed: {result.stderr.strip()}")
                print()
                print("  Try manually:")
                print('    uv tool install --upgrade --reinstall --from "git+https://github.com/ZaxShen/TMB@dev" trustmybot')
        except FileNotFoundError:
            print("  ⚠️  'uv' not found. Trying pip...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade",
                     "trustmybot @ git+https://github.com/ZaxShen/TMB@dev"],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0:
                    print("  ✅ Upgrade complete.")
                else:
                    print(f"  ❌ Upgrade failed: {result.stderr.strip()}")
            except Exception as e:
                print(f"  ❌ Upgrade failed: {e}")
        print()

    # Stable channel: show manual instructions
    else:
        print("  To upgrade, run one of these:")
        print()
        print("    uv tool upgrade trustmybot")
        print()
        print("  or:")
        print()
        print("    pip install --upgrade trustmybot")
        print()


def _extract_chat_signal(content: str) -> tuple[str | None, str | None, str]:
    """Parse chat LLM response for action signals.

    Returns (signal_type, signal_value, display_text) where:
      - signal_type: "command", "quick_task", "plan", or None
      - signal_value: the extracted content from the tag, or None
      - display_text: the response with all action tags stripped (for display)
    """
    import re

    display = content

    # Check for <run_command>...</run_command>
    m = re.search(r'<run_command>(.*?)</run_command>', content, re.DOTALL)
    if m:
        display = re.sub(r'\s*<run_command>.*?</run_command>\s*', '', content, flags=re.DOTALL).strip()
        return ("command", m.group(1).strip(), display)

    # Check for <quick_task>...</quick_task>
    m = re.search(r'<quick_task>(.*?)</quick_task>', content, re.DOTALL)
    if m:
        display = re.sub(r'\s*<quick_task>.*?</quick_task>\s*', '', content, flags=re.DOTALL).strip()
        return ("quick_task", m.group(1).strip(), display)

    # Check for <plan_mode>...</plan_mode>
    m = re.search(r'<plan_mode>(.*?)</plan_mode>', content, re.DOTALL)
    if m:
        display = re.sub(r'\s*<plan_mode>.*?</plan_mode>\s*', '', content, flags=re.DOTALL).strip()
        return ("plan", m.group(1).strip(), display)

    return (None, None, content)


def _dispatch_chat_command(command_str: str, store: Store) -> bool:
    """Dispatch a built-in command from chat mode.

    Returns True if chat should continue after this command,
    False if chat should exit (e.g., plan mode).
    """
    parts = command_str.strip().split(None, 1)
    cmd = parts[0].lower() if parts else ""
    arg = parts[1].strip() if len(parts) > 1 else None

    try:
        # Read-only commands — run immediately
        if cmd == "scan":
            scan()
        elif cmd == "log":
            log_history(int(arg) if arg else None)
        elif cmd == "report":
            if not arg:
                print("[TMB] Usage: report <issue_id>")
                return True
            report(int(arg))
        elif cmd == "tokens":
            tokens(int(arg) if arg else None)
        elif cmd == "version":
            import importlib.metadata
            try:
                v = importlib.metadata.version("trustmybot")
            except importlib.metadata.PackageNotFoundError:
                v = "dev"
            print(f"Trust Me Bro v{v}")

        # Interactive commands — confirm first
        elif cmd == "setup":
            try:
                confirm = input("[TMB] Run setup? (y/n): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                return True
            if confirm in ("y", "yes"):
                setup()
        elif cmd == "upgrade":
            try:
                confirm = input("[TMB] Check for upgrades? (y/n): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                return True
            if confirm in ("y", "yes"):
                upgrade()
        elif cmd == "plan":
            try:
                confirm = input("[TMB] Switch to plan mode? (y/n): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                return True
            if confirm in ("y", "yes"):
                plan()
                return False  # Exit chat after plan
        else:
            print(f"[TMB] Unknown command: {cmd}")
    except (ValueError, TypeError) as e:
        print(f"[TMB] Invalid argument: {e}")

    return True  # Continue chat


def _prefill_goals_and_plan(store: Store, goals_summary: str, session_id: str):
    """Write goals from chat escalation to GOALS.md, then start the plan workflow.

    This is the SOLE EXCEPTION where TMB writes user content to GOALS.md.
    Normally GOALS.md is written only by the human. This exception exists because
    chat-to-plan escalation needs to transfer the conversation context.
    """
    goals_path = docs_dir() / "GOALS.md"

    # Check for existing non-template content
    if goals_path.exists():
        existing = goals_path.read_text().strip()
        # Strip template boilerplate to check for real content
        cleaned = re.sub(r"<!--.*?-->", "", existing, flags=re.DOTALL).strip()
        cleaned = re.sub(
            r"^# Goals\s*\n+Write your goals.*?---\s*",
            "", cleaned, flags=re.DOTALL,
        ).strip()
        if cleaned:
            try:
                confirm = input(
                    "[TMB] GOALS.md has existing content. Overwrite? (y/n): "
                ).strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\n[TMB] Aborted. Your GOALS.md was not changed.")
                return
            if confirm not in ("y", "yes"):
                print("[TMB] Keeping existing GOALS.md. Update it manually, then run `bro plan`.")
                return

    goals_path.parent.mkdir(parents=True, exist_ok=True)
    goals_path.write_text(f"# Goals\n\n{goals_summary}\n")
    print(f"[TMB] Goals written to {goals_path}")

    # Log escalation
    store.log_chat(session_id, "system", f"Escalated to plan mode — GOALS.md prefilled")

    plan()


def chat(initial_message: str | None = None):
    """Interactive chat — the intelligent front door to all bro functionality."""
    import uuid
    from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

    from tmb.config import get_llm, load_prompt, extract_token_usage
    from tmb.tools import get_tools_for_node

    if _is_first_run():
        print("[TMB] First time? Let's get you set up, bro.\n")
        setup()

    _check_llm_config()
    ensure_dirs()
    store = Store()
    project_root = str(get_project_root())
    session_id = uuid.uuid4().hex[:12]

    system_prompt = load_prompt("chat")
    llm = get_llm("planner")
    chat_tools = get_tools_for_node(
        ["file_inspect", "search"], project_root, node_name="planner",
    )
    tool_map = {t.name: t for t in chat_tools} if chat_tools else {}
    llm_with_tools = llm.bind_tools(chat_tools) if chat_tools else llm

    messages = [SystemMessage(content=system_prompt)]

    planner_display = get_role_name("planner").upper()
    print(f"[TMB] Chat mode — session {session_id}")
    print(f"[TMB] Type your questions. Press Ctrl+C or type 'exit' to quit.\n")

    while True:
        try:
            if initial_message is not None:
                user_input = initial_message
                initial_message = None
            else:
                user_input = input(f"[you] ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[TMB] Chat ended.")
            break
        if not user_input or user_input.lower() in ("exit", "quit", "q"):
            print("[TMB] Chat ended.")
            break

        store.log_chat(session_id, "user", user_input)
        messages.append(HumanMessage(content=user_input))

        # Tool loop — let LLM use file_inspect/search before responding
        for _ in range(10):
            response = llm_with_tools.invoke(messages)
            messages.append(response)

            if not hasattr(response, "tool_calls") or not response.tool_calls:
                break

            for tc in response.tool_calls:
                tool_fn = tool_map.get(tc["name"])
                if tool_fn:
                    try:
                        result = tool_fn.invoke(tc["args"])
                    except Exception as e:
                        result = f"[error] {e}"
                    result_str = str(result)
                    if len(result_str) > 8000:
                        result_str = result_str[:8000] + "\n... (truncated)"
                    messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))
                else:
                    messages.append(ToolMessage(
                        content=f"[error] Unknown tool: {tc['name']}",
                        tool_call_id=tc["id"],
                    ))

        # Normalize content
        content = response.content
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        # Parse for action signals
        signal_type, signal_value, display_text = _extract_chat_signal(content)

        # Log and display (always show the clean display_text)
        store.log_chat(session_id, "assistant", content)
        if display_text:
            print(f"\n[{planner_display}] {display_text}\n")

        # Handle action signals
        if signal_type == "command" and signal_value:
            if not _dispatch_chat_command(signal_value, store):
                break  # Command signaled exit (e.g., plan mode)

        elif signal_type == "quick_task" and signal_value:
            try:
                confirm = input("[TMB] Run this task? (y/n): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\n[TMB] Skipped.")
                continue
            if confirm in ("y", "yes"):
                print("[TMB] Working on it...\n")
                _quick_task(store, signal_value)
                print()  # Blank line after task output
                # Add task result context to chat
                messages.append(HumanMessage(
                    content="[system] The task has been executed. Continue chatting."
                ))

        elif signal_type == "plan" and signal_value:
            try:
                confirm = input("[TMB] Switch to plan mode? (y/n): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\n[TMB] Staying in chat.")
                continue
            if confirm in ("y", "yes"):
                _prefill_goals_and_plan(store, signal_value, session_id)
                break


def _check_llm_config():
    """Verify the LLM config will actually work before making any calls.

    Catches the case where a user upgraded from an older version that didn't
    write nodes.yaml during setup — they'd silently fall back to Anthropic
    with no API key and crash.
    """
    import os
    import shutil
    from tmb.config import load_nodes_config, _PROVIDERS

    nodes_yaml = user_cfg_dir() / "nodes.yaml"
    if nodes_yaml.exists():
        # Even with explicit config, verify claude_code CLI is available
        try:
            cfg = load_nodes_config()
            provider = cfg.get("planner", {}).get("model", {}).get("provider", "anthropic")
            if provider == "claude_code" and not shutil.which("claude"):
                print("[TMB] Claude Code CLI not found. Install it or run `bro setup` to pick a different provider.")
                print()
                setup()
        except Exception:
            pass
        return

    # No nodes.yaml → using defaults (Anthropic). Check if that'll work.
    try:
        cfg = load_nodes_config()
        provider = cfg.get("planner", {}).get("model", {}).get("provider", "anthropic")
        _, _, env_var = _PROVIDERS.get(provider, (None, None, None))
        if env_var and not os.environ.get(env_var):
            print(f"[TMB] ⚠️  No LLM configured — no {env_var} found and no nodes.yaml.")
            print(f"[TMB]    Run `bro setup` to pick your LLM provider.")
            print()
            setup()
    except Exception:
        pass


def plan():
    """Full planning workflow invoked via `bro plan`: resumes an open issue or starts fresh."""
    _check_llm_config()

    ensure_dirs()
    store = Store()
    existing = store.get_resumable_issue()

    if existing:
        goals_md = _read_goals_md()

        if goals_md != existing["goals_md"]:
            print(
                f"[TMB] ⚠️ GOALS.md has changed since issue #{existing['id']} was started."
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
        goals_md = _read_goals_md()
        if _check_stale_goals(store, goals_md):
            return
        _fresh_start(store)


def log_history(issue_id: int | None = None):
    """Show issue history from the SQLite store."""
    store = Store()

    if issue_id:
        store.print_summary(issue_id)
        _print_token_summary(store, issue_id)
    else:
        conn = store._conn
        rows = conn.execute(
            "SELECT * FROM issues ORDER BY id DESC LIMIT 20"
        ).fetchall()
        if not rows:
            print("[TMB] No issues found.")
            return
        print(f"\n{'=' * 60}")
        print("  Recent Issues")
        print(f"{'=' * 60}")
        for r in rows:
            icon = {
                "open": "🔧",
                "completed": "✅",
                "failed": "❌",
                "rejected": "🚫",
                "superseded": "🔄",
            }.get(r["status"], "❓")
            print(
                f"  [{icon}] #{r['id']}  {truncate(r['objective'], 50)}  ({r['status']})"
            )
        print()
        print("  View details: tmb log <issue_id>")
        print()


def report(issue_id: int):
    """Export a full human-readable markdown report for an issue."""
    store = Store()
    md = store.export_report_md(issue_id)

    report_path = docs_dir() / f"REPORT-{issue_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md)
    print(f"[TMB] 📄 Report written to {report_path}")
    print(f"       Open it in your editor for full details.")


def tokens(issue_id: int | None = None):
    """Show token usage — for a specific issue or all issues."""
    store = Store()

    if issue_id:
        _print_token_summary(store, issue_id)
        return

    rows = store._conn.execute(
        "SELECT issue_id, node, SUM(input_tokens) as inp, SUM(output_tokens) as outp "
        "FROM token_usage GROUP BY issue_id, node ORDER BY issue_id, node"
    ).fetchall()
    if not rows:
        print("[TMB] No token usage recorded yet.")
        return

    from collections import defaultdict
    by_issue: dict[int, dict] = defaultdict(lambda: {"nodes": {}, "total_in": 0, "total_out": 0})
    grand_in = grand_out = 0
    for r in rows:
        entry = by_issue[r["issue_id"]]
        entry["nodes"][r["node"]] = {"in": r["inp"], "out": r["outp"]}
        entry["total_in"] += r["inp"]
        entry["total_out"] += r["outp"]
        grand_in += r["inp"]
        grand_out += r["outp"]

    print()
    print(f"{'Issue':>7}  {'Node':20s}  {'Input':>12}  {'Output':>12}")
    print(f"{'-' * 7}  {'-' * 20}  {'-' * 12}  {'-' * 12}")
    for iid, data in sorted(by_issue.items()):
        for node, counts in sorted(data["nodes"].items()):
            print(f"{'#' + str(iid):>7}  {node:20s}  {counts['in']:>12,}  {counts['out']:>12,}")
        print(f"{'':>7}  {'subtotal':20s}  {data['total_in']:>12,}  {data['total_out']:>12,}")
        print()
    print(f"{'TOTAL':>7}  {'':20s}  {grand_in:>12,}  {grand_out:>12,}")
    print()


_KNOWN_COMMANDS = {"setup", "log", "report", "tokens", "serve", "evolve", "chat", "plan", "scan", "upgrade", "uninstall", "version", "help", "--help", "-h", "--version", "-v"}


def main():
    if len(sys.argv) == 1:
        chat()
        return

    cmd = sys.argv[1]

    if cmd in ("version", "--version", "-v"):
        import importlib.metadata
        try:
            v = importlib.metadata.version("trustmybot")
        except importlib.metadata.PackageNotFoundError:
            v = "dev"
        print(f"Trust Me Bro v{v}")
        return

    if cmd == "setup":
        setup()
    elif cmd == "log":
        issue_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
        log_history(issue_id)
    elif cmd == "report":
        if len(sys.argv) < 3:
            print("Usage: tmb report <issue_id>")
            sys.exit(1)
        report(int(sys.argv[2]))
    elif cmd == "tokens":
        issue_id = int(sys.argv[2]) if len(sys.argv) > 2 else None
        tokens(issue_id)
    elif cmd == "evolve":
        if len(sys.argv) < 3:
            print('Usage: tmb evolve "instruction"')
            sys.exit(1)
        instruction = " ".join(sys.argv[2:])
        store = Store()
        _evolve(store, instruction)
    elif cmd == "chat":
        chat()
    elif cmd == "plan":
        plan()
    elif cmd == "scan":
        scan()
    elif cmd == "upgrade":
        upgrade()
    elif cmd == "uninstall":
        print()
        print("  To uninstall Trust Me Bro:")
        print()
        print("    uv tool uninstall trustmybot")
        print()
        print("  This removes the bro/bot/tmb commands.")
        print("  Your project files (bro/, .tmb/, .env) are untouched.")
        print()
    elif cmd == "serve":
        from tmb.mcp.server import run_server
        if "--http" in sys.argv:
            idx = sys.argv.index("--http")
            port = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 8000
            print(f"[TMB] 🌐 Starting MCP server (HTTP on port {port})...")
            run_server(transport="http", port=port)
        else:
            run_server(transport="stdio")
    elif cmd not in _KNOWN_COMMANDS:
        instruction = " ".join(sys.argv[1:])
        chat(initial_message=instruction)
    else:
        print("TMB — AI Direction & Execution")
        print()
        print("Usage:")
        print("  bro                               Chat mode (default — ask anything)")
        print("  bro plan                          Full planning workflow (reads bro/GOALS.md)")
        print("  bro chat                          Chat mode (explicit)")
        print('  bro evolve "instruction"           Self-evolution (modify TMB)')
        print("  bro setup                          Interactive project setup")
        print("  bro scan                           Scan project for TMB context")
        print("  bro log                            Show recent issues")
        print("  bro log <id>                       Show issue details + ledger")
        print("  bro report <id>                    Export full report as markdown")
        print("  bro tokens                         Show token usage across all issues")
        print("  bro tokens <id>                    Show token usage for one issue")
        print("  bro serve                          Start MCP server (stdio)")
        print("  bro serve --http 8080              Start MCP server (HTTP)")
        print("  bro upgrade                        Upgrade to latest version")
        print("  bro uninstall                      Uninstall instructions")
        print("  bro version                        Show current version")
        print()
        print("  Tip: just type `bro` and ask — chat can run any command for you.")
        sys.exit(1)
