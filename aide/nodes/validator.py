"""Validator node — verifies executor output against success criteria."""

from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage

from aide.config import get_llm, load_prompt, load_project_config
from aide.state import AgentState


def validator(state: AgentState) -> dict:
    llm = get_llm("validator")
    system_prompt = load_prompt("validator")
    project_cfg = load_project_config()
    max_retries = project_cfg.get("max_retry_per_task", 3)
    store = state.get("store")
    issue_id = state.get("issue_id")

    blueprint = state["blueprint"]
    idx = state["current_task_idx"]
    task = blueprint[idx]
    task_id = task["task_id"]
    total = len(blueprint)
    execution_log = state.get("execution_log", "")
    iteration_count = state.get("iteration_count", 0)

    print(f"[QA] Task {task_id}/{total} — reviewing...")

    verify_prompt = (
        f"Task ID: {task['task_id']}\n"
        f"Success criteria: {task['success_criteria']}\n\n"
        f"Executor's execution log:\n{execution_log}\n\n"
        "Evaluate whether the success criteria are met. "
        "Return your verdict as specified in your instructions."
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=verify_prompt),
    ]

    response = llm.invoke(messages)
    verdict_text = response.content or ""

    is_pass = "PASS" in verdict_text.upper() and "FAIL" not in verdict_text.upper()

    if is_pass:
        next_idx = idx + 1
        is_done = next_idx >= len(blueprint)

        if store and issue_id:
            store.update_task_status(issue_id, task_id, "completed")
            store.log(issue_id, task_id, "validator", "verdict_pass", {
                "evidence": verdict_text[:1000],
            })

        print(f"[QA] Task {task_id} — PASS")

        if is_done:
            print(f"\n[QA] All {total} tasks passed.")

        return {
            "current_task_idx": next_idx,
            "iteration_count": 0,
            "review_feedback": "",
            "execution_log": "",
            "messages": state.get("messages", []) + [response],
            "next_node": "__end__" if is_done else "executor",
        }

    new_iteration = iteration_count + 1

    if store and issue_id:
        store.log(issue_id, task_id, "validator", "verdict_fail", {
            "attempt": new_iteration,
            "max_retries": max_retries,
            "feedback": verdict_text[:1000],
        })

    if new_iteration >= max_retries:
        if store and issue_id:
            store.update_task_status(issue_id, task_id, "failed")
            store.log(issue_id, task_id, "validator", "max_retries_exceeded", {
                "attempts": new_iteration,
            })
        print(f"[QA] Task {task_id} — FAIL (attempt {new_iteration}/{max_retries}, escalating to Architect)")
        return {
            "iteration_count": new_iteration,
            "review_feedback": f"Max retries ({max_retries}) exceeded. Validator feedback:\n{verdict_text}",
            "messages": state.get("messages", []) + [response],
            "next_node": "architect",
        }

    print(f"[QA] Task {task_id} — FAIL (attempt {new_iteration}/{max_retries}, retrying)")
    return {
        "iteration_count": new_iteration,
        "review_feedback": verdict_text,
        "messages": state.get("messages", []) + [response],
        "next_node": "executor",
    }
