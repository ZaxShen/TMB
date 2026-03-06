"""Planner nodes — planning and execution plan generation.

Two graph nodes:
  planner_plan          — explores codebase, then generates BLUEPRINT.md, FLOWCHART.md, QA_PLAN.md
  planner_execution_plan — generates EXECUTION.md (after approval)
"""

from __future__ import annotations

import json

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from baymax.config import get_llm, load_prompt, load_nodes_config, get_project_root, get_role_name, _BAYMAX_ROOT
from baymax.permissions import assert_baymax_write
from baymax.state import AgentState
from baymax.store import Store
from baymax.tools import get_tools_for_node

_MAX_EXPLORE_ROUNDS = 10


def _normalize_content(content) -> str:
    if not content:
        return ""
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


def _write_doc(name: str, content: str):
    doc_dir = _BAYMAX_ROOT / "doc"
    doc_dir.mkdir(parents=True, exist_ok=True)
    path = doc_dir / name
    assert_baymax_write(path)
    path.write_text(content)


def _run_tool_loop(llm_with_tools, messages, tool_map, max_rounds):
    """Run a multi-turn tool loop, returning the final response."""
    response = None
    for _ in range(max_rounds):
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
                print(f"  [planner:{tc['name']}] done")
                messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))
            else:
                messages.append(ToolMessage(
                    content=f"[error] Unknown tool: {tc['name']}",
                    tool_call_id=tc["id"],
                ))
    return response, messages


EXPLORE_INSTRUCTION = (
    "Before creating the blueprint, explore the existing codebase to understand its "
    "architecture, key modules, entry points, dependencies, and patterns.\n\n"
    "Use `file_read` to read important source files and `search` to find patterns.\n"
    "Focus on:\n"
    "- Entry points (main files, app factories, route definitions)\n"
    "- Core business logic modules\n"
    "- Data models / schemas\n"
    "- Configuration and dependency files\n"
    "- Existing test structure\n\n"
    "When you have a solid understanding of the codebase, summarize your findings "
    "and then say: EXPLORATION COMPLETE\n\n"
    "Your summary should cover:\n"
    "1. Tech stack and frameworks\n"
    "2. Project structure and key modules\n"
    "3. Current architecture patterns\n"
    "4. Areas relevant to the goals\n"
)

BLUEPRINT_INSTRUCTION = (
    "Based on the goals, discussion, codebase exploration, and any feedback, "
    "produce a Blueprint as a JSON array.\n\n"
    "Each element must have: branch_id (str), description (str), tools_required (list[str]), "
    "skills_required (list[str]), success_criteria (str).\n\n"
    "## Branch ID Convention\n"
    "Branch IDs are **hierarchical strings** that encode semantic relationships:\n"
    "- Root branches: \"1\", \"2\", \"3\"\n"
    "- Sub-branches: \"1.1\", \"1.2\" (children of branch 1)\n"
    "- Deeper: \"1.1.1\" (child of branch 1.1)\n\n"
    "If an EXISTING TASK TREE is provided below, assign IDs that reflect relationships:\n"
    "- New work extending existing branch \"2\" → use \"2.1\", \"2.2\"\n"
    "- Completely new, unrelated work → use the next unused root ID\n\n"
    "If NO existing tasks exist, start from \"1\".\n\n"
    "## Skills\n"
    "If AVAILABLE SKILLS are listed below, assign relevant skill names to each task's "
    "`skills_required` array. Only assign skills genuinely useful for the task. "
    "If no skill fits, leave the array empty.\n\n"
    "Return ONLY the JSON array, no other text."
)

FLOWCHART_INSTRUCTION = (
    "Based on the blueprint you just created and your understanding of the codebase, "
    "produce a high-level architecture or data-flow diagram in Mermaid syntax. "
    "Use `graph TD` or `flowchart TD`. "
    "The diagram should show the main components/steps and their relationships. "
    "Return ONLY the Mermaid code block (```mermaid ... ```), no other text."
)

QA_PLAN_INSTRUCTION = (
    "Based on the blueprint and your understanding of the codebase, produce a QA plan in Markdown. "
    "For each task (or group of related tasks), specify:\n"
    "- **What to test**: the specific behavior or output to verify\n"
    "- **How to test**: concrete commands, assertions, or checks\n"
    "- **Risk level**: high/medium/low — focus detail on high-risk items\n"
    "- **Edge cases**: any tricky scenarios the QA engineer should watch for\n\n"
    "Return ONLY the Markdown content, no JSON wrapping."
)

def _exec_plan_instruction():
    return (
        f"The {get_role_name('owner')} has approved the blueprint. Now produce a detailed execution plan.\n"
        "For each task, write step-by-step instructions that a junior developer can follow.\n"
        "Use your tools to read relevant source files if you need to understand existing code.\n"
        "Include:\n"
        "- Exact commands to run\n"
        "- File paths to create or modify\n"
        "- Expected outputs at each step\n"
        "- Dependencies on previous tasks\n\n"
        "Format as Markdown with a ## section per task using the branch_id: `## Task <branch_id>: <title>`.\n"
        "Example: `## Task 1.1: Add email verification`\n"
        "Return ONLY the Markdown content."
    )


def planner_plan(state: AgentState) -> dict:
    """Explore codebase, then generate BLUEPRINT.md, FLOWCHART.md, and QA_PLAN.md."""
    node_cfg = load_nodes_config().get("planner", {})
    project_root = str(get_project_root())
    llm = get_llm("planner")
    system_prompt = load_prompt("planner")
    store = Store()
    issue_id = state.get("issue_id")

    tool_names = node_cfg.get("tools", [])
    tools = get_tools_for_node(tool_names, project_root, node_name="planner")
    tool_map = {t.name: t for t in tools} if tools else {}

    if tools:
        llm_with_tools = llm.bind_tools(tools)
    else:
        llm_with_tools = llm

    planner_display = get_role_name("planner").upper()
    owner_display = get_role_name("owner")
    objective = state["objective"]
    feedback = state.get("review_feedback", "")
    escalation_log = state.get("execution_log", "")
    project_context = state.get("project_context", "")
    discussion = state.get("discussion", "")

    is_replan = bool(feedback)

    # ── 0. Explore the codebase ──────────────────────────────
    exploration_summary = ""
    if tools and not is_replan:
        print(f"[{planner_display}] Exploring codebase...")
        explore_parts = []
        if project_context:
            explore_parts.append(f"## Project Context\n{project_context}")
        explore_parts.append(f"## Goals\n{objective}")
        if discussion:
            explore_parts.append(f"## Discussion with {owner_display}\n{discussion}")
        explore_parts.append(EXPLORE_INSTRUCTION)

        explore_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content="\n\n".join(explore_parts)),
        ]

        explore_response, explore_messages = _run_tool_loop(
            llm_with_tools, explore_messages, tool_map, _MAX_EXPLORE_ROUNDS,
        )
        exploration_summary = _normalize_content(explore_response.content)
        store.log(issue_id, None, "planner", "codebase_explored", {
            "summary_length": len(exploration_summary),
        }, summary="Explored codebase structure and key modules")
        print(f"[{planner_display}] Exploration complete ({len(exploration_summary)} chars)")
    elif is_replan:
        print(f"[{planner_display}] Re-planning based on feedback...")
    else:
        print(f"[{planner_display}] Building blueprint from discussion...")

    # ── 0b. Review pending skills ─────────────────────────────
    pending_skills = store.get_skills_pending_review()
    if pending_skills:
        print(f"[{planner_display}] Reviewing {len(pending_skills)} pending skills...")
        for ps in pending_skills:
            review_prompt = (
                f"An agent created a skill during execution. Review it and decide "
                f"whether to APPROVE or REJECT.\n\n"
                f"**Name**: {ps['name']}\n"
                f"**Description**: {ps['description']}\n"
                f"**When to use**: {ps.get('when_to_use', '(not specified)')}\n"
                f"**When not to use**: {ps.get('when_not_to_use', '(not specified)')}\n"
                f"**Created by**: {ps['created_by']}\n"
                f"**Tags**: {ps.get('tags', '[]')}\n\n"
            )
            skill_path = _BAYMAX_ROOT / ps.get("file_path", "")
            if skill_path.exists():
                content = skill_path.read_text()
                if len(content) > 3000:
                    content = content[:3000] + "\n... (truncated)"
                review_prompt += f"**Content**:\n```\n{content}\n```\n\n"
            review_prompt += (
                "Reply with ONLY one of:\n"
                "- APPROVE — if the skill is accurate, useful, and well-scoped\n"
                "- REJECT — if it's inaccurate, too vague, redundant, or could mislead agents\n"
                "Then a one-line reason."
            )
            review_msgs = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=review_prompt),
            ]
            review_resp = llm.invoke(review_msgs)
            verdict = _normalize_content(review_resp.content).strip().upper()
            if verdict.startswith("APPROVE"):
                store.activate_skill(ps["name"])
                store.log(issue_id, None, "planner", "skill_approved", {
                    "skill": ps["name"],
                }, summary=f"Approved skill: {ps['name']}")
                print(f"  [{planner_display}] Approved skill: {ps['name']}")
            else:
                store.deprecate_skill(ps["name"])
                store.log(issue_id, None, "planner", "skill_rejected", {
                    "skill": ps["name"], "reason": verdict[:200],
                }, summary=f"Rejected skill: {ps['name']}")
                print(f"  [{planner_display}] Rejected skill: {ps['name']}")

    # ── 1. Generate Blueprint ────────────────────────────────
    existing_tree = store.get_all_root_tasks()
    available_skills = store.get_all_skills()
    parts = []
    if project_context:
        parts.append(f"## Project Context\n{project_context}")
    parts.append(f"## Goals\n{objective}")
    if discussion:
        parts.append(f"## Discussion with {owner_display}\n{discussion}")
    if exploration_summary:
        parts.append(f"## Codebase Exploration\n{exploration_summary}")
    if existing_tree:
        tree_lines = [f"- **{t['branch_id']}**: {t['title']} [{t['status']}] (issue #{t['issue_id']}: {t['objective'][:60]})"
                      for t in existing_tree]
        parts.append(f"## Existing Task Tree\n" + "\n".join(tree_lines))
    if available_skills:
        skill_lines = []
        for s in available_skills:
            eff = s.get("effectiveness")
            eff_str = f"{eff:.0%}" if eff is not None else "n/a"
            tier = s.get("trust_tier", "curated")
            line = f"- **{s['name']}** [{tier}] (eff: {eff_str}, uses: {s.get('uses', 0)}): {s['description']}"
            if s.get("when_to_use"):
                line += f"\n  - Use when: {s['when_to_use']}"
            if s.get("when_not_to_use"):
                line += f"\n  - Avoid when: {s['when_not_to_use']}"
            skill_lines.append(line)
        parts.append("## Available Skills\n" + "\n".join(skill_lines)
                      + "\n\nPrefer skills with higher effectiveness. "
                      "Avoid assigning skills with low effectiveness (< 30%).")
    if feedback:
        parts.append(f"## Previous Feedback / Escalation\n{feedback}")
    if escalation_log:
        parts.append(f"## Execution Log\n{escalation_log}")
    parts.append(BLUEPRINT_INSTRUCTION)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(parts)),
    ]

    response = llm.invoke(messages)
    raw = _normalize_content(response.content)

    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        blueprint = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        print(f"[{planner_display}] WARNING: Failed to parse blueprint JSON. Raw response ({len(raw)} chars):")
        print(raw[:500])
        blueprint = []

    store.create_tasks(issue_id, blueprint)
    if is_replan:
        store.log(issue_id, None, "planner", "blueprint_revised", {
            "reason": feedback[:500],
            "task_count": len(blueprint),
        }, summary=f"Blueprint revised: {len(blueprint)} tasks")

    blueprint_md = store.export_blueprint_md(issue_id, blueprint)
    _write_doc("BLUEPRINT.md", blueprint_md)
    print(f"[{planner_display}] Blueprint saved to doc/BLUEPRINT.md ({len(blueprint)} tasks)")

    # ── 2. Generate Flowchart ────────────────────────────────
    print(f"[{planner_display}] Generating flowchart...")
    fc_parts = [
        f"## Blueprint\n```json\n{json.dumps(blueprint, indent=2)}\n```",
        f"## Goals\n{objective}",
    ]
    if exploration_summary:
        fc_parts.append(f"## Codebase Understanding\n{exploration_summary}")
    fc_parts.append(FLOWCHART_INSTRUCTION)

    fc_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(fc_parts)),
    ]
    fc_response = llm.invoke(fc_messages)
    fc_raw = _normalize_content(fc_response.content)

    flowchart_md = (
        f"# Flowchart — Issue #{issue_id}\n\n"
        f"**Objective**: {objective[:120]}\n\n"
        f"{fc_raw}\n"
    )
    _write_doc("FLOWCHART.md", flowchart_md)
    store.log(issue_id, None, "planner", "flowchart_generated", {},
             summary="Generated FLOWCHART.md")
    print(f"[{planner_display}] Flowchart saved to doc/FLOWCHART.md")

    # ── 3. Generate QA Plan ──────────────────────────────────
    print(f"[{planner_display}] Generating QA plan...")
    qa_parts = [
        f"## Blueprint\n```json\n{json.dumps(blueprint, indent=2)}\n```",
        f"## Goals\n{objective}",
    ]
    if exploration_summary:
        qa_parts.append(f"## Codebase Understanding\n{exploration_summary}")
    qa_parts.append(QA_PLAN_INSTRUCTION)

    qa_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(qa_parts)),
    ]
    qa_response = llm.invoke(qa_messages)
    qa_raw = _normalize_content(qa_response.content)

    qa_plan_md = (
        f"# QA Plan — Issue #{issue_id}\n\n"
        f"**Objective**: {objective[:120]}\n\n"
        f"---\n\n"
        f"{qa_raw}\n"
    )
    _write_doc("QA_PLAN.md", qa_plan_md)
    store.log(issue_id, None, "planner", "qa_plan_generated", {},
             summary="Generated QA_PLAN.md")
    print(f"[{planner_display}] QA plan saved to doc/QA_PLAN.md")

    print(f"[{planner_display}] Planning complete: {len(blueprint)} tasks")

    return {
        "blueprint": blueprint,
        "current_task_idx": 0,
        "iteration_count": 0,
        "review_feedback": "",
        "execution_log": "",
        "messages": state.get("messages", []) + [response],
        "next_node": "human_review",
    }


def _quick_task_instruction():
    return (
        "You are handling a quick task directly — no downstream agents involved.\n"
        f"The {get_role_name('owner')} gave you a single instruction to execute yourself.\n\n"
        "Steps:\n"
        "1. Use `file_read` and `search` to understand the current state of relevant files.\n"
        "2. Use `file_write` to make the changes directly.\n"
        "3. If the instruction involves updating a doc/ file (FLOWCHART, BLUEPRINT, etc.), "
        "read the existing file first, understand the codebase, then rewrite it.\n\n"
        "When done, provide a short summary of what you changed."
    )


def planner_quick_task(instruction: str, project_context: str, issue_id: int):
    """Planner handles a simple task directly — no graph, no executor, no validator."""
    node_cfg = load_nodes_config().get("planner", {})
    project_root = str(get_project_root())
    llm = get_llm("planner")
    system_prompt = load_prompt("planner")
    store = Store()

    quick_tools_names = list(set(node_cfg.get("tools", []) + ["file_write"]))
    tools = get_tools_for_node(quick_tools_names, project_root, node_name="planner")
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    parts = []
    if project_context:
        parts.append(f"## Project Context\n{project_context}")
    parts.append(f"## Instruction\n{instruction}")
    parts.append(_quick_task_instruction())

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(parts)),
    ]

    planner_display = get_role_name("planner").upper()
    print(f"[{planner_display}] Working on quick task...")
    response, messages = _run_tool_loop(
        llm_with_tools, messages, tool_map, _MAX_EXPLORE_ROUNDS,
    )
    result = _normalize_content(response.content)

    store.log(issue_id, None, "planner", "quick_task_completed", {},
             summary=f"Quick: {instruction[:150]}")
    print(f"[{planner_display}] Done.")
    return result


def _evolve_plan_instruction():
    return (
        "You are in **self-evolution mode**. You are modifying the Baymax framework itself.\n\n"
        f"The {get_role_name('owner')} has given you an instruction to improve or change the Baymax engine.\n"
        "You have full read access to Baymax's own source code.\n\n"
        "Steps:\n"
        "1. Use `file_read` and `search` to explore the Baymax codebase.\n"
        "2. Understand the current architecture — modules, tools, permissions, engine, prompts, config.\n"
        "3. Produce a structured **Evolution Plan** in Markdown:\n\n"
        "```\n"
        "# Evolution Plan\n\n"
        "## Instruction\n"
        "{the instruction}\n\n"
        "## Analysis\n"
        "{what you found in the codebase}\n\n"
        "## Proposed Changes\n"
        "- **file**: path — **change**: description\n"
        "- ...\n\n"
        "## Risk Assessment\n"
        "{what could break, edge cases}\n\n"
        "## Rollback\n"
        "git revert HEAD\n"
        "```\n\n"
        "Return ONLY the Markdown plan, nothing else."
    )


def _evolve_execute_instruction():
    return (
        "You are in **self-evolution mode** — executing an approved evolution plan.\n\n"
        f"The {get_role_name('owner')} has reviewed and approved your plan. Now execute it.\n\n"
        "Rules:\n"
        "- Use `file_read` to read files before modifying them.\n"
        "- Use `file_write` to make changes.\n"
        "- Use `shell` only if you need to run commands (e.g. formatting, testing).\n"
        "- Follow the approved plan precisely. Do not deviate.\n"
        "- After all changes, provide a summary of what was modified.\n"
    )


def planner_evolve(instruction: str, baymax_context: str, issue_id: int) -> str:
    """Exploration + plan phase of self-evolution. Returns the plan markdown.

    Runs inside evolve_context() — Baymax/** blacklist is lifted for reads.
    """
    node_cfg = load_nodes_config().get("evolve", load_nodes_config().get("planner", {}))
    llm = get_llm("planner")
    system_prompt = load_prompt("planner")
    store = Store()

    baymax_root_str = str(_BAYMAX_ROOT)
    tool_names = ["file_read", "search"]
    tools = get_tools_for_node(tool_names, baymax_root_str, node_name="planner")
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    parts = []
    if baymax_context:
        parts.append(f"## Baymax Codebase Context\n{baymax_context}")
    parts.append(f"## Instruction\n{instruction}")
    parts.append(_evolve_plan_instruction())

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(parts)),
    ]

    planner_display = get_role_name("planner").upper()
    print(f"[{planner_display}] Exploring Baymax codebase for evolution plan...")
    response, messages = _run_tool_loop(
        llm_with_tools, messages, tool_map, _MAX_EXPLORE_ROUNDS,
    )
    plan = _normalize_content(response.content)

    _write_doc("EVOLUTION.md", plan)
    store.log(issue_id, None, "planner", "evolve_plan_generated", {
        "instruction": instruction[:300],
    }, summary=f"Evolution plan: {instruction[:120]}")

    print(f"[{planner_display}] Evolution plan saved to doc/EVOLUTION.md")
    return plan


def planner_evolve_execute(
    instruction: str, plan: str, baymax_context: str, issue_id: int,
) -> str:
    """Execution phase of self-evolution. Applies the approved plan.

    Runs inside evolve_context() — full Baymax read/write access.
    """
    node_cfg = load_nodes_config().get("evolve", load_nodes_config().get("planner", {}))
    llm = get_llm("planner")
    system_prompt = load_prompt("planner")
    store = Store()

    baymax_root_str = str(_BAYMAX_ROOT)
    tool_names = list(set(
        node_cfg.get("tools", ["file_read", "search"]) + ["file_write", "shell"]
    ))
    tools = get_tools_for_node(tool_names, baymax_root_str, node_name="planner")
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    parts = [
        f"## Baymax Codebase Context\n{baymax_context}" if baymax_context else "",
        f"## Instruction\n{instruction}",
        f"## Approved Evolution Plan\n{plan}",
        _evolve_execute_instruction(),
    ]
    parts = [p for p in parts if p]

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(parts)),
    ]

    planner_display = get_role_name("planner").upper()
    print(f"[{planner_display}] Executing evolution plan...")
    response, messages = _run_tool_loop(
        llm_with_tools, messages, tool_map, 15,
    )
    result = _normalize_content(response.content)

    store.log(issue_id, None, "planner", "evolve_executed", {
        "instruction": instruction[:300],
    }, summary=f"Executed evolution: {instruction[:120]}")

    print(f"[{planner_display}] Evolution execution complete.")
    return result


def planner_execution_plan(state: AgentState) -> dict:
    """Generate EXECUTION.md — detailed step-by-step plan for executors.

    Uses tools to read relevant source files for accurate step-by-step instructions.
    """
    node_cfg = load_nodes_config().get("planner", {})
    project_root = str(get_project_root())
    llm = get_llm("planner")
    system_prompt = load_prompt("planner")
    store = Store()
    issue_id = state.get("issue_id")

    tool_names = node_cfg.get("tools", [])
    tools = get_tools_for_node(tool_names, project_root, node_name="planner")
    tool_map = {t.name: t for t in tools} if tools else {}

    if tools:
        llm_with_tools = llm.bind_tools(tools)
    else:
        llm_with_tools = llm

    planner_display = get_role_name("planner").upper()
    blueprint = state["blueprint"]
    objective = state["objective"]
    project_context = state.get("project_context", "")

    print(f"[{planner_display}] Generating execution plan...")

    parts = []
    if project_context:
        parts.append(f"## Project Context\n{project_context}")
    parts.append(f"## Goals\n{objective}")
    parts.append(f"## Approved Blueprint\n```json\n{json.dumps(blueprint, indent=2)}\n```")
    parts.append(_exec_plan_instruction())

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(parts)),
    ]

    response, messages = _run_tool_loop(
        llm_with_tools, messages, tool_map, _MAX_EXPLORE_ROUNDS,
    )
    raw = _normalize_content(response.content)

    execution_md = (
        f"# Execution Plan — Issue #{issue_id}\n\n"
        f"**Objective**: {objective[:120]}\n\n"
        f"---\n\n"
        f"{raw}\n"
    )
    _write_doc("EXECUTION.md", execution_md)
    store.log(issue_id, None, "planner", "execution_plan_generated", {
        "task_count": len(blueprint),
    }, summary=f"Generated EXECUTION.md for {len(blueprint)} tasks")
    print(f"[{planner_display}] Execution plan saved to doc/EXECUTION.md")

    return {
        "messages": state.get("messages", []) + [response],
        "next_node": "executor",
    }
