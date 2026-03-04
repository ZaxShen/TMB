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

    blueprint = state["blueprint"]
    idx = state["current_task_idx"]
    task = blueprint[idx]
    execution_log = state.get("execution_log", "")
    iteration_count = state.get("iteration_count", 0)

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
        return {
            "current_task_idx": next_idx,
            "iteration_count": 0,
            "review_feedback": "",
            "execution_log": "",
            "messages": state.get("messages", []) + [response],
            "next_node": "__end__" if is_done else "executor",
        }

    new_iteration = iteration_count + 1
    if new_iteration >= max_retries:
        return {
            "iteration_count": new_iteration,
            "review_feedback": f"Max retries ({max_retries}) exceeded. Validator feedback:\n{verdict_text}",
            "messages": state.get("messages", []) + [response],
            "next_node": "architect",
        }

    return {
        "iteration_count": new_iteration,
        "review_feedback": verdict_text,
        "messages": state.get("messages", []) + [response],
        "next_node": "executor",
    }
