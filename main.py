"""AIDE CLI entry point."""

from __future__ import annotations

import sys
import json

from aide.engine import build_graph
from aide.config import load_project_config


def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <objective>")
        print('Example: python main.py "Add unit tests for the auth module"')
        sys.exit(1)

    objective = " ".join(sys.argv[1:])
    project_cfg = load_project_config()

    print(f"[AIDE] Project: {project_cfg['name']}")
    print(f"[AIDE] Objective: {objective}")
    print()

    graph = build_graph()

    state = graph.invoke(
        {
            "objective": objective,
            "blueprint": [],
            "current_task_idx": 0,
            "execution_log": "",
            "review_feedback": "",
            "iteration_count": 0,
            "messages": [],
            "next_node": "",
        }
    )

    # After interrupt: show the blueprint for CTO review
    blueprint = state.get("blueprint", [])
    if blueprint:
        print("[ARCHITECT] Blueprint for your review:")
        print(json.dumps(blueprint, indent=2))
    else:
        print("[ARCHITECT] No blueprint was generated.")
        sys.exit(1)

    print()
    approval = input("[CTO] Approve this blueprint? (yes/no): ").strip().lower()
    if approval not in ("yes", "y"):
        print("[AIDE] Blueprint rejected. Exiting.")
        sys.exit(0)

    print()
    print("[AIDE] Blueprint approved. Starting execution...")
    print()

    # Resume after interrupt — the graph continues from executor
    state = graph.invoke(state)

    print()
    print("[AIDE] Workflow complete.")


if __name__ == "__main__":
    main()
