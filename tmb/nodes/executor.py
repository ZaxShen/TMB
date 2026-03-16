"""Executor node — executes the current blueprint task using tools."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("tmb.executor")

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from tmb.config import get_llm, load_prompt, load_nodes_config, get_project_root, get_role_name, extract_token_usage
from tmb.paths import TMB_ROOT, user_skills_dir
from tmb.utils import truncate, fit_line
from tmb.state import AgentState
from tmb.store import Store
from tmb.tools import get_tools_for_node
from tmb.types import TokenAccumulator

_MAX_TOOL_ROUNDS = 15
_MAX_TOOL_OUTPUT_CHARS = 20_000
_CONTEXT_BUDGET_CHARS = 600_000  # ~150K tokens; leaves headroom under 200K limit


def _get_execution_plan(store: Store, issue_id: int, branch_id: str) -> str:
    """Read the per-task execution plan from SQLite."""
    return store.get_task_execution_plan(issue_id, branch_id)


def _estimate_context_chars(messages: list) -> int:
    """Sum character lengths across all messages for budget tracking."""
    total = 0
    for m in messages:
        content = m.content if hasattr(m, "content") else str(m)
        if isinstance(content, list):
            total += sum(len(str(block)) for block in content)
        else:
            total += len(str(content))
    return total


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


def _resolve_skill_path(file_path: str):
    """Resolve a skill file path, checking seed dir then user dir."""
    p = TMB_ROOT / file_path
    if p.exists():
        return p
    p = user_skills_dir() / file_path.replace("skills/", "", 1)
    if p.exists():
        return p
    return None


def _load_skills(store: Store, skill_names: list[str]) -> str:
    """Load skill file contents for the given names, return combined text."""
    if not skill_names:
        return ""
    skills = store.get_skills_by_names(skill_names)
    parts = []
    for s in skills:
        resolved = _resolve_skill_path(s["file_path"])
        if resolved:
            parts.append(resolved.read_text().strip())
    return "\n\n---\n\n".join(parts)


def _detect_escalation(content) -> bool:
    """Detect escalation signal using XML tags, with keyword fallback.

    Priority order:
      1. <status>escalate</status> XML tag
      2. Word-boundary keyword \\bescalate\\b
      3. Default: False
    """
    text = _normalize_content(content)
    # Tier 1: XML <status> tag
    if re.search(r"<status>\s*escalate\s*</status>", text, re.IGNORECASE):
        return True
    # Tier 2: word-boundary keyword
    if re.search(r"\bescalate\b", text, re.IGNORECASE):
        logger.info(
            "Escalation detected via keyword fallback (no <status> tag) | first 200 chars: %s",
            text[:200]
        )
        return True
    return False


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

    exec_plan_section = _get_execution_plan(store, issue_id, branch_id)

    skill_names = task.get("skills_required", [])
    if not skill_names and db_task:
        raw_sr = db_task.get("skills_required", "[]")
        try:
            skill_names = json.loads(raw_sr) if isinstance(raw_sr, str) else raw_sr
        except (json.JSONDecodeError, TypeError):
            skill_names = []
    skills_text = _load_skills(store, skill_names) if skill_names else ""

    total = len(blueprint)
    executor_display = get_role_name("executor").upper()
    planner_display = get_role_name("planner")
    planner_validate_display = get_role_name("planner")
    if is_retry:
        print(fit_line(f"[{executor_display}] 🔄 [{branch_id}] {total} tasks — retrying:", description))
    else:
        print(fit_line(f"[{executor_display}] 🔧 [{branch_id}] {total} tasks — starting:", description))

    store.update_task_status(issue_id, branch_id, "in_progress", increment_attempts=True)
    task_title = task.get("title") or truncate(description, 80)
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
    token_accum = TokenAccumulator()
    budget_exceeded = False

    for _round in range(_MAX_TOOL_ROUNDS):
        ctx_chars = _estimate_context_chars(messages)
        if ctx_chars > _CONTEXT_BUDGET_CHARS:
            budget_exceeded = True
            messages.append(HumanMessage(
                content=(
                    f"[system] Context budget exceeded ({ctx_chars:,} chars). "
                    f"Stop using tools and return your structured log now."
                )
            ))
            response = llm_with_tools.invoke(messages)
            messages.append(response)
            usage = extract_token_usage(response)
            token_accum.add(usage)
            break

        response = llm_with_tools.invoke(messages)
        messages.append(response)

        usage = extract_token_usage(response)
        token_accum.add(usage)

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

                is_truncated = len(result_str) > _MAX_TOOL_OUTPUT_CHARS
                store.log_tool_call(
                    issue_id, branch_id, _round, tc["name"],
                    tc.get("args", {}), result_str, is_truncated=is_truncated,
                )

                if is_truncated:
                    llm_result = (
                        result_str[:_MAX_TOOL_OUTPUT_CHARS]
                        + f"\n\n... (truncated \u2014 {len(result_str):,} chars total. "
                        f"Full output saved to DB.)"
                    )
                else:
                    llm_result = result_str

                tool_outputs.append(f"[{tc['name']}] {llm_result}")
                print(f"  [{tc['name']}] done ({len(result_str):,} chars)")
                messages.append(ToolMessage(content=llm_result, tool_call_id=tc["id"]))
            else:
                messages.append(ToolMessage(
                    content=f"[error] Unknown tool: {tc['name']}",
                    tool_call_id=tc["id"],
                ))

    store.log_tokens(issue_id, "executor", token_accum.input_tokens, token_accum.output_tokens)

    if budget_exceeded:
        store.log(issue_id, branch_id, "executor", "context_budget_exceeded", {
            "chars": _estimate_context_chars(messages),
            "rounds_used": _round + 1,
        }, summary=f"Context budget hit after {_round + 1} rounds")

    execution_log = _normalize_content(response.content)
    if tool_outputs:
        execution_log += "\n\nTool outputs:\n" + "\n".join(tool_outputs)

    is_escalation = _detect_escalation(response.content)

    if is_escalation:
        store.update_task_status(issue_id, branch_id, "escalated")
        store.log(issue_id, branch_id, "executor", "task_escalated", {
            "reason": execution_log[:1000],
        }, summary=f"Escalated: {task_title}")
        print(f"[{executor_display}] ⚠️ [{branch_id}] — ESCALATED to {planner_display}")
    else:
        store.log(issue_id, branch_id, "executor", "task_executed", {
            "output": execution_log[:2000],
            "tool_calls": len(tool_outputs),
        }, summary=f"Executed: {task_title} ({len(tool_outputs)} tool calls)")
        print(f"[{executor_display}] ✅ [{branch_id}] — execution complete, sending to {planner_validate_display}")

    return {
        "execution_log": execution_log,
        "messages": state.get("messages", []) + [response],
        "next_node": "__end__" if is_escalation else "planner_validate",
    }
