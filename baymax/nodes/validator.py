"""Validator node — verifies executor output against success criteria."""

from __future__ import annotations

import json
import re

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from baymax.config import get_llm, load_prompt, load_project_config, load_nodes_config, get_project_root, get_role_name
from baymax.paths import BAYMAX_ROOT, docs_dir, user_skills_dir
from baymax.state import AgentState
from baymax.store import Store
from baymax.tools import get_tools_for_node

_MAX_TOOL_ROUNDS = 10


def _normalize_content(content) -> str:
    if not content:
        return ""
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _extract_verdict(text: str) -> bool:
    """Determine PASS/FAIL from validator output.

    Strategy (in priority order):
      1. Parse JSON block and read the "verdict" field
      2. Regex for "verdict": "PASS" / "FAIL" pattern
      3. Fallback: first occurrence of standalone PASS or FAIL keyword
    """
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        try:
            obj = json.loads(json_match.group(1))
            v = str(obj.get("verdict", "")).upper()
            if v in ("PASS", "FAIL"):
                return v == "PASS"
        except (json.JSONDecodeError, AttributeError):
            pass

    field_match = re.search(r'"verdict"\s*:\s*"(PASS|FAIL)"', text, re.IGNORECASE)
    if field_match:
        return field_match.group(1).upper() == "PASS"

    upper = text.upper()
    pass_pos = upper.find("PASS")
    fail_pos = upper.find("FAIL")
    if pass_pos >= 0 and fail_pos < 0:
        return True
    if fail_pos >= 0 and pass_pos < 0:
        return False
    if pass_pos >= 0 and fail_pos >= 0:
        return pass_pos < fail_pos

    return False


def _read_qa_plan() -> str:
    """Read QA_PLAN.md from baymax-docs/ if it exists."""
    path = docs_dir() / "QA_PLAN.md"
    if path.exists():
        return path.read_text()
    return ""


def _resolve_skill_path(file_path: str):
    """Resolve a skill file path, checking seed dir then user dir."""
    p = BAYMAX_ROOT / file_path
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


def _record_skill_outcomes(store: Store, skill_names: list[str], is_pass: bool):
    """Update effectiveness counters for every skill used in this task."""
    for name in skill_names:
        msg = store.record_skill_outcome(name, is_pass)
        if msg:
            print(f"[{get_role_name('validator').upper()}] {msg}")


def _archive_task_from_execution_md(store: Store, issue_id: int, branch_id: str):
    """Log that a task's execution plan has been consumed.

    Plans are stored per-task in SQLite from the start, so no file
    parsing is needed. This just logs the archive event.
    """
    store.log(issue_id, branch_id, "validator", "execution_task_archived", {},
             summary=f"Archived [{branch_id}]")


def validator(state: AgentState) -> dict:
    node_cfg = load_nodes_config().get("validator", {})
    project_root = str(get_project_root())
    llm = get_llm("validator")
    system_prompt = load_prompt("validator")
    project_cfg = load_project_config()
    max_retries = project_cfg.get("max_retry_per_task", 3)
    store = Store()
    issue_id = state.get("issue_id")

    tool_names = node_cfg.get("tools", [])
    tools = get_tools_for_node(tool_names, project_root, node_name="validator")
    if tools:
        llm_with_tools = llm.bind_tools(tools)
    else:
        llm_with_tools = llm

    blueprint = state["blueprint"]
    idx = state["current_task_idx"]
    task = blueprint[idx]
    branch_id = task["branch_id"]
    total = len(blueprint)
    execution_log = state.get("execution_log", "")
    iteration_count = state.get("iteration_count", 0)

    qa_plan = _read_qa_plan()

    skill_names = task.get("skills_required", [])
    if not skill_names:
        db_task = store.get_task_row(issue_id, branch_id)
        if db_task:
            raw_sr = db_task.get("skills_required", "[]")
            try:
                skill_names = json.loads(raw_sr) if isinstance(raw_sr, str) else raw_sr
            except (json.JSONDecodeError, TypeError):
                skill_names = []
    skills_text = _load_skills(store, skill_names) if skill_names else ""

    validator_display = get_role_name("validator").upper()
    planner_display = get_role_name("planner")
    print(f"[{validator_display}] [{branch_id}] {total} tasks — reviewing...")

    verify_prompt = (
        f"Branch ID: {branch_id}\n"
        f"Success criteria: {task['success_criteria']}\n\n"
    )
    if skills_text:
        verify_prompt += f"## Reference Skills\n{skills_text}\n\n"
    if qa_plan:
        verify_prompt += f"QA Plan (relevant sections):\n{qa_plan}\n\n"
    verify_prompt += (
        f"Executor's execution log:\n{execution_log}\n\n"
        "Evaluate whether the success criteria are met. "
        "Use your tools (e.g. shell) to run verification commands if needed. "
        "Return your verdict as specified in your instructions."
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=verify_prompt),
    ]

    tool_map = {t.name: t for t in tools} if tools else {}

    response = None
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
                print(f"  [{validator_display}:{tc['name']}] done")
                messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))
            else:
                messages.append(ToolMessage(
                    content=f"[error] Unknown tool: {tc['name']}",
                    tool_call_id=tc["id"],
                ))

    verdict_text = _normalize_content(response.content)

    is_pass = _extract_verdict(verdict_text)

    _record_skill_outcomes(store, skill_names, is_pass)

    if is_pass:
        next_idx = idx + 1
        is_done = next_idx >= len(blueprint)

        store.update_task_status(issue_id, branch_id, "completed")
        store.archive_task_qa_results(issue_id, branch_id, verdict_text[:2000])
        store.log(issue_id, branch_id, "validator", "verdict_pass", {
            "evidence": verdict_text[:1000],
        }, summary=f"PASS: [{branch_id}]")

        _archive_task_from_execution_md(store, issue_id, branch_id)

        print(f"[{validator_display}] [{branch_id}] — PASS")

        if is_done:
            print(f"\n[{validator_display}] All {total} tasks passed.")

        return {
            "current_task_idx": next_idx,
            "iteration_count": 0,
            "review_feedback": "",
            "execution_log": "",
            "messages": state.get("messages", []) + [response],
            "next_node": "__end__" if is_done else "executor",
        }

    new_iteration = iteration_count + 1

    store.log(issue_id, branch_id, "validator", "verdict_fail", {
        "attempt": new_iteration,
        "max_retries": max_retries,
        "feedback": verdict_text[:1000],
    }, summary=f"FAIL: [{branch_id}] (attempt {new_iteration}/{max_retries})")

    if new_iteration >= max_retries:
        store.update_task_status(issue_id, branch_id, "failed")
        store.log(issue_id, branch_id, "validator", "max_retries_exceeded", {
            "attempts": new_iteration,
        }, summary=f"Max retries hit for [{branch_id}]")
        print(f"[{validator_display}] [{branch_id}] — FAIL (attempt {new_iteration}/{max_retries}, escalating to {planner_display})")
        return {
            "iteration_count": new_iteration,
            "review_feedback": f"Max retries ({max_retries}) exceeded. Validator feedback:\n{verdict_text}",
            "messages": state.get("messages", []) + [response],
            "next_node": "planner",
        }

    print(f"[{validator_display}] [{branch_id}] — FAIL (attempt {new_iteration}/{max_retries}, retrying)")
    return {
        "iteration_count": new_iteration,
        "review_feedback": verdict_text,
        "messages": state.get("messages", []) + [response],
        "next_node": "executor",
    }
