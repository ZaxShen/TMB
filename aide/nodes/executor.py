"""Executor node — executes the current blueprint task using tools."""

from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from aide.config import get_llm, load_prompt, load_nodes_config, get_project_root
from aide.state import AgentState
from aide.store import Store
from aide.tools import get_tools_for_node

_MAX_TOOL_ROUNDS = 15


def _normalize_content(content) -> str:
    """Anthropic sometimes returns content as a list of blocks."""
    if not content:
        return ""
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def executor(state: AgentState) -> dict:
    node_cfg = load_nodes_config()["executor"]
    project_root = str(get_project_root())
    store = Store()
    issue_id = state.get("issue_id")

    llm = get_llm("executor")
    system_prompt = load_prompt("executor")

    tool_names = node_cfg.get("tools", [])
    tools = get_tools_for_node(tool_names, project_root, node_name="executor")

    if tools:
        llm_with_tools = llm.bind_tools(tools)
    else:
        llm_with_tools = llm

    blueprint = state["blueprint"]
    idx = state["current_task_idx"]

    if idx >= len(blueprint):
        return {
            "execution_log": "All tasks completed.",
            "next_node": "__end__",
        }

    task = blueprint[idx]
    task_id = task["task_id"]
    feedback = state.get("review_feedback", "")
    is_retry = bool(feedback)

    db_task = store.get_task_row(issue_id, task_id)
    description = db_task["description"] if db_task else task["description"]
    success_criteria = db_task["success_criteria"] if db_task else task["success_criteria"]

    total = len(blueprint)
    if is_retry:
        print(f"[SWE] Task {task_id}/{total} — retrying: {description[:60]}")
    else:
        print(f"[SWE] Task {task_id}/{total} — starting: {description[:60]}")

    store.update_task_status(issue_id, task_id, "in_progress", increment_attempts=True)
    store.log(issue_id, task_id, "executor", "task_started" if not is_retry else "task_retried", {
        "description": description,
    })

    task_prompt = (
        f"Execute the following task:\n\n"
        f"Task ID: {task_id}\n"
        f"Description: {description}\n"
        f"Tools available: {task.get('tools_required', [])}\n"
        f"Success criteria: {success_criteria}\n"
    )

    if feedback:
        task_prompt += f"\nPrevious attempt feedback:\n{feedback}\n"

    task_prompt += (
        "\nExecute the task. If the task is unclear or blocked, "
        "set status to 'escalate' with a reason. "
        "Return your structured log as specified in your instructions."
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=task_prompt),
    ]

    tool_map = {t.name: t for t in tools} if tools else {}
    tool_outputs = []

    for _round in range(_MAX_TOOL_ROUNDS):
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
                tool_outputs.append(f"[{tc['name']}] {result_str}")
                print(f"  [{tc['name']}] done")
                messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))
            else:
                messages.append(ToolMessage(
                    content=f"[error] Unknown tool: {tc['name']}",
                    tool_call_id=tc["id"],
                ))

    execution_log = _normalize_content(response.content)
    if tool_outputs:
        execution_log += "\n\nTool outputs:\n" + "\n".join(tool_outputs)

    is_escalation = "escalate" in execution_log.lower()

    if is_escalation:
        store.update_task_status(issue_id, task_id, "escalated")
        store.log(issue_id, task_id, "executor", "task_escalated", {
            "reason": execution_log[:1000],
        })
        print(f"[SWE] Task {task_id} — ESCALATED to Architect")
    else:
        store.log(issue_id, task_id, "executor", "task_executed", {
            "output": execution_log[:2000],
            "tool_calls": len(tool_outputs),
        })
        print(f"[SWE] Task {task_id} — execution complete, sending to QA")

    return {
        "execution_log": execution_log,
        "messages": state.get("messages", []) + [response],
        "next_node": "architect" if is_escalation else "validator",
    }
