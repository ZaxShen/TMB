"""Executor node — executes the current blueprint task using tools."""

from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage

from aide.config import get_llm, load_prompt, load_nodes_config, load_project_config
from aide.state import AgentState
from aide.tools import get_tools_for_node


def executor(state: AgentState) -> dict:
    node_cfg = load_nodes_config()["executor"]
    project_cfg = load_project_config()
    project_root = project_cfg.get("root_dir", ".")

    llm = get_llm("executor")
    system_prompt = load_prompt("executor")

    tool_names = node_cfg.get("tools", [])
    tools = get_tools_for_node(tool_names, project_root)

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
    feedback = state.get("review_feedback", "")

    task_prompt = (
        f"Execute the following task:\n\n"
        f"Task ID: {task['task_id']}\n"
        f"Description: {task['description']}\n"
        f"Tools available: {task['tools_required']}\n"
        f"Success criteria: {task['success_criteria']}\n"
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

    response = llm_with_tools.invoke(messages)

    # Check for tool calls — if the LLM wants to use tools, execute them
    tool_outputs = []
    if hasattr(response, "tool_calls") and response.tool_calls:
        tool_map = {t.name: t for t in tools}
        for tc in response.tool_calls:
            tool_fn = tool_map.get(tc["name"])
            if tool_fn:
                result = tool_fn.invoke(tc["args"])
                tool_outputs.append(f"[{tc['name']}] {result}")

    execution_log = response.content or ""
    if tool_outputs:
        execution_log += "\n\nTool outputs:\n" + "\n".join(tool_outputs)

    is_escalation = "escalate" in execution_log.lower()

    return {
        "execution_log": execution_log,
        "messages": state.get("messages", []) + [response],
        "next_node": "architect" if is_escalation else "validator",
    }
