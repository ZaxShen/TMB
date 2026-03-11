"""TMB CLI entry point.

Usage:
  tmb                               Full workflow (reads bro/GOALS.md)
  tmb "update FLOWCHART"            Quick task (full pipeline, no interactive steps)
  tmb evolve "instruction"          Self-evolution (modify TMB itself)
  tmb setup                         Interactive project setup
  tmb chat                          Interactive chat with the planner
  tmb scan                          Scan project for TMB context
  tmb log                           Show recent issues
  tmb log <id>                      Show issue details + ledger
  tmb report <id>                   Export full report as markdown
  tmb serve                         Start MCP server (stdio)
  tmb serve --http 8080             Start MCP server (HTTP)
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from tmb.config import load_project_config, get_project_root, get_role_name
from tmb.paths import TMB_ROOT, docs_dir, runtime_dir, user_cfg_dir, ensure_dirs
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
        print(f"[TMB] Created {goals_path}")
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
        print(f"[TMB] {goals_path} is empty or still has the template.")
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
    print(f"[{planner_display}] Blueprint ({len(tasks)} tasks) — see bro/BLUEPRINT.md")
    for t in tasks:
        bid = t.get("branch_id") or t.get("task_id", "?")
        label = t.get("title") or t["description"][:80]
        print(f"  [{bid}] {label}")
    print()


def _approve_blueprint(store: Store, issue_id: int) -> bool:
    owner_display = get_role_name("owner")
    approval = input(f"[{owner_display}] Approve this blueprint? (yes/no): ").strip().lower()
    if approval not in ("yes", "y"):
        store.log(issue_id, None, "owner", "blueprint_rejected", {},
                  summary=f"{owner_display} rejected blueprint")
        store.close_issue(issue_id, "rejected")
        print("[TMB] Blueprint rejected. Issue closed.")
        return False

    store.log(issue_id, None, "owner", "blueprint_approved", {},
              summary=f"{owner_display} approved blueprint")
    print()
    print("[TMB] Blueprint approved. Generating execution plan...")
    print("-" * 40)
    return True


def _quick_task(store: Store, instruction: str):
    """Quick-task flow: same pipeline as full workflow, minus discussion and manual approval.

    gatekeeper → planner_plan (auto-approved) → execution plans → executor ↔ planner_validate
    """
    project_cfg = load_project_config()
    project_root = get_project_root()

    _maybe_suggest_scan(store, project_root)

    objective = instruction[:120].strip()
    issue_id = store.create_issue(objective, instruction)

    print(f"[TMB] Quick task — Issue #{issue_id}: {objective}")
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
        print(f"[{get_role_name('planner').upper()}] No blueprint was generated.")
        store.close_issue(issue_id, "failed")
        return

    _show_blueprint(blueprint)

    store.log(issue_id, None, "owner", "blueprint_approved", {},
              summary="Auto-approved (quick task)")
    print("[TMB] Blueprint auto-approved (quick task)")
    print("-" * 40)

    state = graph.invoke(None, config=thread)

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
    print(f"[GATEKEEPER] Scanned {len(tree.splitlines())} paths in TMB/")
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
            print("[EVOLVE] Working tree clean — no snapshot needed.")
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
        print(f"[EVOLVE] Git snapshot committed: {msg}")
        return True
    except Exception as e:
        print(f"[EVOLVE] Warning: git snapshot failed ({e}). Proceeding anyway.")
        return False


def _health_check() -> bool:
    """Verify TMB can still be imported after self-evolution."""
    print("[EVOLVE] Running health check...")
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import tmb; import tmb.engine; import tmb.store"],
            cwd=str(TMB_ROOT), capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"[EVOLVE] HEALTH CHECK FAILED — import error:")
            print(result.stderr[:500])
            return False
    except Exception as e:
        print(f"[EVOLVE] HEALTH CHECK FAILED — {e}")
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

    print("[EVOLVE] Health check passed.")
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
        print("[EVOLVE] Planner produced no plan. Aborting.")
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
        print(f"[EVOLVE] Self-evolution complete. Issue #{issue_id} closed.")
    else:
        store.log(issue_id, None, "system", "evolve_failed", {},
                  summary=f"Self-evolution failed health check: {instruction[:120]}")
        store.close_issue(issue_id, "failed")
        print()
        print("!" * 60)
        print("[EVOLVE] HEALTH CHECK FAILED. Your changes may have broken TMB.")
        print("[EVOLVE] To rollback:  cd TMB && git revert HEAD")
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


def _finalize_issue(store: Store, issue_id: int):
    """Check task statuses and close the issue appropriately."""
    tasks = store.get_tasks(issue_id)
    if not tasks:
        store.close_issue(issue_id, "completed")
        return

    all_done = all(t["status"] == "completed" for t in tasks)
    if all_done:
        store.close_issue(issue_id, "completed")
    else:
        stuck = [t for t in tasks if t["status"] in ("failed", "escalated")]
        pending = [t for t in tasks if t["status"] in ("pending", "in_progress")]
        if stuck:
            print(
                f"[TMB] {len(stuck)} task(s) failed/escalated. "
                f"Issue #{issue_id} stays open — re-run to retry."
            )
        elif pending:
            print(
                f"[TMB] {len(pending)} task(s) still pending. "
                f"Issue #{issue_id} stays open — re-run to continue."
            )

    print("-" * 40)
    store.print_summary(issue_id)
    _print_token_summary(store, issue_id)
    print(f"[TMB] See {docs_dir().name}/ for DISCUSSION, BLUEPRINT, FLOWCHART, and EXECUTION.")


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
    graph.invoke(
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
        }
    )

    _finalize_issue(store, issue_id)


# ── Fresh Start ──────────────────────────────────────────────


def _maybe_suggest_scan(store: Store, project_root):
    """Hint user to run 'tmb scan' if the project has source files but no scan data."""
    if store.file_registry_count() > 0:
        return
    root = Path(project_root)
    has_source = any(
        root.glob(pat) for pat in ["*.py", "*.js", "*.ts", "*.go", "*.rs", "*.java",
                                    "package.json", "pyproject.toml", "Cargo.toml", "go.mod"]
    )
    if has_source:
        print("[TMB] Existing project detected. Run 'uv run tmb scan' for better planning context.\n")


def _fresh_start(store: Store):
    """Full workflow: goals → discuss → plan (blueprint + flowchart) → approve → execution plan → execute."""
    project_cfg = load_project_config()
    project_root = get_project_root()

    _maybe_suggest_scan(store, project_root)

    goals_md = _read_goals_md()
    objective = _derive_objective(goals_md)
    issue_id = store.create_issue(objective, goals_md)

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
        print(f"[{get_role_name('planner').upper()}] No blueprint was generated.")
        store.close_issue(issue_id, "failed")
        sys.exit(1)

    _show_blueprint(blueprint)
    print(f"[TMB] Review {docs_dir().name}/BLUEPRINT.md and {docs_dir().name}/FLOWCHART.md")
    print()

    if not _approve_blueprint(store, issue_id):
        sys.exit(0)

    state = graph.invoke(None, config=thread)

    _finalize_issue(store, issue_id)


# ── Resume ───────────────────────────────────────────────────


def _resume(store: Store, issue: dict):
    """Phase router — detect where the previous run stopped and continue."""
    issue_id = issue["id"]
    goals_md = issue["goals_md"]
    project_cfg = load_project_config()
    project_root = get_project_root()

    print(f"[TMB] Resuming issue #{issue_id}: {issue['objective']}")
    print(f"[TMB] Project: {project_cfg['name']}  |  Root: {project_root}")

    project_context = None

    def ensure_context() -> str:
        nonlocal project_context
        if project_context is None:
            project_context = _scan_project_context(store, issue_id, goals_md)
        return project_context

    if not store.has_event(issue_id, "discussion_complete"):
        print("[TMB] Phase: discussion (incomplete)")
        ctx = ensure_context()
        from tmb.nodes.discussion import run_discussion

        run_discussion(goals_md, ctx, store, issue_id)

    tasks = store.get_tasks(issue_id)
    if not tasks:
        print("[TMB] Phase: planning (pending)")
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
            print(f"[{get_role_name('planner').upper()}] No blueprint was generated.")
            store.close_issue(issue_id, "failed")
            sys.exit(1)

        _show_blueprint(blueprint)

        if not _approve_blueprint(store, issue_id):
            sys.exit(0)

        state = graph.invoke(None, config=thread)
        _finalize_issue(store, issue_id)
        return

    if not store.has_event(issue_id, "blueprint_approved"):
        print("[TMB] Phase: approval (pending)")
        _show_blueprint(tasks)
        if not _approve_blueprint(store, issue_id):
            sys.exit(0)

    if not store.has_event(issue_id, "execution_plan_generated"):
        print("[TMB] Phase: execution plan (pending)")
        ctx = ensure_context()
        blueprint = _tasks_to_blueprint(tasks)
        _run_execution_plan(store, issue_id, goals_md, ctx, blueprint)

    actionable = store.get_first_actionable_task(issue_id)
    if not actionable:
        print("[TMB] All tasks already completed.")
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
        f"[TMB] Phase: execution ([{actionable['branch_id']}] {completed_count}/{total}, "
        f"{completed_count} already done)"
    )
    print("-" * 40)

    discussion_md = store.export_discussion_md(issue_id)
    ctx = ensure_context()
    _run_execution(store, issue_id, goals_md, ctx, discussion_md, blueprint, start_idx)


# ── CLI Commands ─────────────────────────────────────────────


def setup():
    """Interactive setup — writes .tmb/config/project.yaml and .env."""
    from pathlib import Path

    print("[TMB] Setup")
    print("=" * 40)
    print()

    ensure_dirs()
    project_root = get_project_root()
    detected_name = project_root.name

    name = input(f"Project name [{detected_name}]: ").strip() or detected_name
    test_cmd = input("Test command [pytest]: ").strip() or "pytest"
    max_retries = input("Max retries per task [3]: ").strip() or "3"

    print()
    print("Role naming — choose a preset or keep defaults:")
    print("  1) Generic  (Project Owner → Planner → Executor)")
    print("  2) IT Company  (Chief Architect → Architect → SWE)")
    print("  3) Custom  (enter your own names)")
    role_choice = input("Choice [1]: ").strip() or "1"

    roles_cfg: dict = {}
    if role_choice == "2":
        roles_cfg = {
            "preset": "it-company",
            "owner": "Chief Architect",
            "planner": "Architect",
            "executor": "SWE",
        }
    elif role_choice == "3":
        roles_cfg["owner"] = input("  Human role name [Project Owner]: ").strip() or "Project Owner"
        roles_cfg["planner"] = input("  Planner role name [Planner]: ").strip() or "Planner"
        roles_cfg["executor"] = input("  Executor role name [Executor]: ").strip() or "Executor"

    config = {
        "name": name,
        "test_command": test_cmd,
        "max_retry_per_task": int(max_retries),
    }
    if roles_cfg:
        config["roles"] = roles_cfg

    config_path = user_cfg_dir() / "project.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"  Wrote {config_path}")

    goals_path = docs_dir() / "GOALS.md"
    if not goals_path.exists():
        goals_path.parent.mkdir(parents=True, exist_ok=True)
        goals_path.write_text(
            "# Goals\n\n"
            "Write your goals below. The Planner will read this file and discuss with you.\n\n"
            "---\n\n"
        )
        print(f"  Created {goals_path}")

    _PROVIDER_MENU = [
        ("1", "Anthropic (Claude)",  "ANTHROPIC_API_KEY", "anthropic",  None),
        ("2", "OpenAI (GPT)",        "OPENAI_API_KEY",    "openai",     None),
        ("3", "Google (Gemini)",     "GOOGLE_API_KEY",    "google",     "tmb[google]"),
        ("4", "Groq",               "GROQ_API_KEY",      "groq",       "tmb[groq]"),
        ("5", "Mistral",            "MISTRAL_API_KEY",   "mistral",    "tmb[mistral]"),
        ("6", "DeepSeek",           "DEEPSEEK_API_KEY",  "deepseek",   "tmb[deepseek]"),
        ("7", "Ollama (local)",     None,                "ollama",     "tmb[ollama]"),
        ("s", "Skip",               None,                None,         None),
    ]

    env_path = project_root / ".env"
    if env_path.exists():
        print(f"  .env already exists at {env_path} — skipping.")
    else:
        print()
        print("Which LLM provider will you use?")
        for key, label, _, _, _ in _PROVIDER_MENU:
            print(f"  {key}) {label}")
        choice = input("Choice [1]: ").strip() or "1"

        selected = next((m for m in _PROVIDER_MENU if m[0] == choice), None)
        env_lines = []
        if selected and selected[0] != "s":
            _, label, env_var, provider_name, extra_pkg = selected
            if env_var:
                api_key = input(f"  {env_var}: ").strip()
                if api_key:
                    env_lines.append(f"{env_var}={api_key}")
            if extra_pkg:
                print(f"  Note: install the provider package with:  uv add {extra_pkg}")

        if env_lines:
            env_path.write_text("\n".join(env_lines) + "\n")
            print(f"  Wrote {env_path}")
        elif choice != "s":
            print("  No API key entered — set it in .env before running.")

    # ── Web Search ────────────────────────────────────────────
    print()
    print("=== Web Search ===")
    print()
    print("  TMB can search the web during planning.")
    print("  Tavily (tavily.com) gives the best results — free tier: 1000 searches/month.")
    print("  Without a key, DuckDuckGo is used as a free fallback.")
    print()
    tavily_key = input("  TAVILY_API_KEY (Enter to skip): ").strip()
    if tavily_key:
        existing_env = env_path.read_text() if env_path.exists() else ""
        if "TAVILY_API_KEY" not in existing_env:
            with open(env_path, "a") as f:
                f.write(f"\nTAVILY_API_KEY={tavily_key}\n")
            print("  Added Tavily key to .env")
    else:
        print("  Skipped — DuckDuckGo fallback will be used for web search.")

    # ── MCP Connections ──────────────────────────────────────
    print()
    print("=== MCP Connections (optional) ===")
    print()
    print("  TMB can connect to external services via MCP.")
    print()
    print("  [1] Notion    — read/create pages, search workspace")
    print("  [2] GitHub    — issues, PRs, code search")
    print("  [3] Slack     — send messages, read channels")
    print("  [s] Skip")
    print()
    mcp_choice = input("  Select (comma-separated, e.g. 1,2) [s]: ").strip().lower() or "s"

    if mcp_choice != "s":
        mcp_servers = {}
        existing_env = env_path.read_text() if env_path.exists() else ""
        new_env_lines = []

        choices = [c.strip() for c in mcp_choice.split(",")]

        if "1" in choices:
            token = input("  Notion API token: ").strip()
            if token:
                mcp_servers["notion"] = {
                    "command": "npx",
                    "args": ["-y", "@notionhq/notion-mcp-server"],
                    "env": {"NOTION_TOKEN": "${NOTION_TOKEN}"},
                    "agents": ["planner"],
                }
                if "NOTION_TOKEN" not in existing_env:
                    new_env_lines.append(f"NOTION_TOKEN={token}")

        if "2" in choices:
            token = input("  GitHub token: ").strip()
            if token:
                mcp_servers["github"] = {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_TOKEN": "${GITHUB_TOKEN}"},
                    "agents": ["planner", "executor"],
                }
                if "GITHUB_TOKEN" not in existing_env:
                    new_env_lines.append(f"GITHUB_TOKEN={token}")

        if "3" in choices:
            token = input("  Slack Bot token: ").strip()
            if token:
                mcp_servers["slack"] = {
                    "command": "npx",
                    "args": ["-y", "@anthropic/slack-mcp-server"],
                    "env": {"SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}"},
                    "agents": ["planner"],
                }
                if "SLACK_BOT_TOKEN" not in existing_env:
                    new_env_lines.append(f"SLACK_BOT_TOKEN={token}")

        if mcp_servers:
            mcp_config_path = user_cfg_dir() / "mcp.yaml"
            mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
            mcp_data = yaml.safe_load(mcp_config_path.read_text()) if mcp_config_path.exists() else {}
            existing_servers = mcp_data.get("servers") or {}
            existing_servers.update(mcp_servers)
            mcp_data["servers"] = existing_servers
            mcp_config_path.write_text(yaml.dump(mcp_data, default_flow_style=False, sort_keys=False))
            print(f"  Wrote {mcp_config_path}")

        if new_env_lines:
            with open(env_path, "a") as f:
                f.write("\n" + "\n".join(new_env_lines) + "\n")
            print(f"  Updated .env with MCP tokens")

    # ── Project-level pyproject.toml ─────────────────────────
    project_toml = project_root / "pyproject.toml"
    if not project_toml.exists():
        print()
        print("No pyproject.toml found at project root.")
        create = input("  Create one with TMB as a dependency? (yes/no) [yes]: ").strip().lower()
        if create in ("", "yes", "y"):
            tmb_rel = TMB_ROOT.resolve().relative_to(project_root.resolve())
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
            print(f"  Wrote {project_toml}")
            print(f"  Run `uv sync` at {project_root} to install.")

    print()
    print("[TMB] Setup complete.")
    dd = docs_dir().name
    print(f"  1. Write your goals in {dd}/GOALS.md")
    print("  2. Run: uv run tmb")
    print()


def _is_first_run() -> bool:
    """Detect whether setup has ever been run for this project."""
    return not (user_cfg_dir() / "project.yaml").exists()


def scan():
    """Scan the project directory and populate TMB's DB with file registry + context."""
    from tmb.scanner import scan_project

    ensure_dirs()
    store = Store()
    project_root = get_project_root()

    print(f"[TMB] Scanning project: {project_root}")
    print("-" * 40)

    stats = scan_project(project_root, store)

    print(f"[TMB] Scan complete:")
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


def chat():
    """Interactive chat with the planner — read-only exploration, with optional planning escalation."""
    import uuid
    from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

    from tmb.config import get_llm, load_prompt, extract_token_usage
    from tmb.tools import get_tools_for_node

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
            user_input = input(f"[you] ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[TMB] Chat ended.")
            break
        if not user_input or user_input.lower() in ("exit", "quit", "q"):
            print("[TMB] Chat ended.")
            break

        store.log_chat(session_id, "user", user_input)
        messages.append(HumanMessage(content=user_input))

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

        content = response.content
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        store.log_chat(session_id, "assistant", content)
        print(f"\n[{planner_display}] {content}\n")

        if re.search(r"ready to plan\?", content, re.IGNORECASE):
            try:
                confirm = input("[TMB] Escalate to planning? (y/n): ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\n[TMB] Chat ended.")
                break
            if confirm in ("y", "yes"):
                chat_history = store.get_chat_history(session_id)
                summary_parts = []
                for msg in chat_history:
                    prefix = "User" if msg["role"] == "user" else "Planner"
                    summary_parts.append(f"{prefix}: {msg['content']}")
                chat_summary = "\n".join(summary_parts[-20:])

                instruction = (
                    f"Based on the following chat discussion, plan and execute:\n\n"
                    f"{chat_summary}"
                )

                issue_id = store.create_issue(
                    instruction[:120].strip(), instruction,
                )
                store.mark_chat_escalated(session_id, issue_id)
                store.log_chat(session_id, "system", f"Escalated to issue #{issue_id}")

                print(f"\n[TMB] Created issue #{issue_id} from chat — starting planning...")
                print("-" * 40)
                _quick_task(store, instruction)
                break


def run():
    """Phase-aware entry point: resumes an open issue or starts fresh."""
    if _is_first_run():
        print("[TMB] First run detected — running setup.\n")
        setup()

    ensure_dirs()
    store = Store()
    existing = store.get_open_issue()

    if existing:
        goals_md = _read_goals_md()

        if goals_md != existing["goals_md"]:
            print(
                f"[TMB] GOALS.md has changed since issue #{existing['id']} was started."
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
        print("  View details: tmb log <issue_id>")
        print()


def report(issue_id: int):
    """Export a full human-readable markdown report for an issue."""
    store = Store()
    md = store.export_report_md(issue_id)

    report_path = docs_dir() / f"REPORT-{issue_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(md)
    print(f"[TMB] Report written to {report_path}")
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


_KNOWN_COMMANDS = {"setup", "log", "report", "tokens", "serve", "evolve", "chat", "scan", "help", "--help", "-h"}


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
    elif cmd == "scan":
        scan()
    elif cmd == "serve":
        from tmb.mcp.server import run_server
        if "--http" in sys.argv:
            idx = sys.argv.index("--http")
            port = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 8000
            print(f"[TMB] Starting MCP server (HTTP on port {port})...")
            run_server(transport="http", port=port)
        else:
            run_server(transport="stdio")
    elif cmd not in _KNOWN_COMMANDS:
        instruction = " ".join(sys.argv[1:])
        store = Store()
        _quick_task(store, instruction)
    else:
        print("TMB — AI Direction & Execution")
        print()
        print("Usage:")
        print("  tmb                               Full workflow (reads bro/GOALS.md)")
        print('  tmb "update FLOWCHART"             Quick task (full pipeline)')
        print('  tmb evolve "instruction"           Self-evolution (modify TMB)')
        print("  tmb setup                          Interactive project setup")
        print("  tmb chat                           Interactive chat with the planner")
        print("  tmb scan                           Scan project for TMB context")
        print("  tmb log                            Show recent issues")
        print("  tmb log <id>                       Show issue details + ledger")
        print("  tmb report <id>                    Export full report as markdown")
        print("  tmb tokens                         Show token usage across all issues")
        print("  tmb tokens <id>                    Show token usage for one issue")
        print("  tmb serve                          Start MCP server (stdio)")
        print("  tmb serve --http 8080              Start MCP server (HTTP)")
        sys.exit(1)
