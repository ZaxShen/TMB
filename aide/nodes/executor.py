"""Executor node — executes the current blueprint task using tools."""

from __future__ import annotations

import json

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from aide.config import get_llm, load_prompt, load_nodes_config, get_project_root, _AIDE_ROOT
from aide.state import AgentState
from aide.store import Store
from aide.tools import get_tools_for_node

_MAX_TOOL_ROUNDS = 15


def _read_execution_plan_section(branch_id: str) -> str:
    """Extract the section for a specific task from doc/EXECUTION.md."""
    path = _AIDE_ROOT / "doc" / "EXECUTION.md"
    if not path.exists():
        return ""
    content = path.read_text()
    task_header = f"## Task {branch_id}"
    lines = content.split("\n")

    task_start = None
    task_end = None
    for i, line in enumerate(lines):
        if line.strip().startswith(task_header):
            task_start = i
        elif task_start is not None and line.strip().startswith("## Task "):
            task_end = i
            break

    if task_start is None:
        return ""

    if task_end is None:
        task_end = len(lines)

    return "\n".join(lines[task_start:task_end]).strip()


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


def _load_skills(store: Store, skill_names: list[str]) -> str:
    """Load skill file contents for the given names, return combined text."""
    if not skill_names:
        return ""
    skills = store.get_skills_by_names(skill_names)
    parts = []
    for s in skills:
        skill_path = _AIDE_ROOT / s["file_path"]
        if skill_path.exists():
            parts.append(skill_path.read_text().strip())
    return "\n\n---\n\n".join(parts)


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
    branch_id = task["branch_id"]
    feedback = state.get("review_feedback", "")
    is_retry = bool(feedback)

    db_task = store.get_task_row(issue_id, branch_id)
    description = db_task["description"] if db_task else task["description"]
    success_criteria = db_task["success_criteria"] if db_task else task["success_criteria"]

    exec_plan_section = _read_execution_plan_section(branch_id)

    skill_names = task.get("skills_required", [])
    if not skill_names and db_task:
        raw_sr = db_task.get("skills_required", "[]")
        try:
            skill_names = json.loads(raw_sr) if isinstance(raw_sr, str) else raw_sr
        except (json.JSONDecodeError, TypeError):
            skill_names = []
    skills_text = _load_skills(store, skill_names) if skill_names else ""

    total = len(blueprint)
    if is_retry:
        print(f"[SWE] [{branch_id}] {total} tasks — retrying: {description[:60]}")
    else:
        print(f"[SWE] [{branch_id}] {total} tasks — starting: {description[:60]}")

    store.update_task_status(issue_id, branch_id, "in_progress", increment_attempts=True)
    task_title = task.get("title") or description[:80]
    store.log(issue_id, branch_id, "executor",
              "task_started" if not is_retry else "task_retried",
              {"description": description},
              summary=f"{'Retry' if is_retry else 'Start'}: {task_title}")

    task_prompt = (
        f"Execute the following task:\n\n"
        f"Branch ID: {branch_id}\n"
        f"Description: {description}\n"
        f"Tools available: {task.get('tools_required', [])}\n"
        f"Success criteria: {success_criteria}\n"
    )

    if skills_text:
        task_prompt += f"\n## Reference Skills\n{skills_text}\n"

    if exec_plan_section:
        task_prompt += f"\nDetailed execution plan:\n{exec_plan_section}\n"

    if feedback:
        task_prompt += f"\nPrevious attempt feedback:\n{feedback}\n"

    task_prompt += (
        "\nExecute the task. If the task is unclear or blocked, "
        "or if the execution plan steps don't match reality, "
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
        store.update_task_status(issue_id, branch_id, "escalated")
        store.log(issue_id, branch_id, "executor", "task_escalated", {
            "reason": execution_log[:1000],
        }, summary=f"Escalated: {task_title}")
        print(f"[SWE] [{branch_id}] — ESCALATED to Architect")
    else:
        store.log(issue_id, branch_id, "executor", "task_executed", {
            "output": execution_log[:2000],
            "tool_calls": len(tool_outputs),
        }, summary=f"Executed: {task_title} ({len(tool_outputs)} tool calls)")
        print(f"[SWE] [{branch_id}] — execution complete, sending to QA")

    return {
        "execution_log": execution_log,
        "messages": state.get("messages", []) + [response],
        "next_node": "architect" if is_escalation else "validator",
    }
