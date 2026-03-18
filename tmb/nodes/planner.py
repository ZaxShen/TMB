"""Planner nodes — planning, validation, and execution plan generation.

Graph nodes:
  planner_plan           — explores codebase, generates BLUEPRINT.md (+ optional FLOWCHART.md)
  planner_execution_plan — generates per-task execution plans in SQLite (after approval)
  planner_validate       — validates executor output, may update FLOWCHART.md on architectural changes
"""

from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET

logger = logging.getLogger("tmb.planner")

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage

from tmb.config import get_llm, load_prompt, load_nodes_config, load_project_config, get_project_root, get_role_name, extract_token_usage, safe_llm_invoke, LLMConnectionError
from tmb.paths import TMB_ROOT, docs_dir, SEED_SKILLS_DIR, user_skills_dir
from tmb.utils import truncate
from tmb.state import AgentState
from tmb.store import Store
from tmb.tools import get_tools_for_node
from tmb.types import TokenAccumulator

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
    dd = docs_dir()
    dd.mkdir(parents=True, exist_ok=True)
    path = dd / name
    path.write_text(content)


_PLANNER_CONTEXT_BUDGET_CHARS = 600_000  # ~150K tokens; matches executor budget


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


def _run_tool_loop(llm_with_tools, messages, tool_map, max_rounds, label: str = "",
                   token_accum: "TokenAccumulator | None" = None,
                   max_context_chars: int = _PLANNER_CONTEXT_BUDGET_CHARS,
                   max_wall_seconds: float = 600.0,
                   audit_store=None, audit_issue_id=None, audit_branch_id=None,
                   audit_from_node: str = "planner"):
    """Run a multi-turn tool loop, returning the final response.

    Shows live progress on a single line, overwritten after each tool call.
    If *token_accum* is provided, accumulates token counts across calls.
    Stops early if estimated context exceeds *max_context_chars* or if
    wall-clock time exceeds *max_wall_seconds*.
    """
    import sys
    import time
    start = time.monotonic()
    counts: dict[str, int] = {}
    response = None
    prefix = f"  [{label}] " if label else "  "

    def _print_progress(final: bool = False):
        elapsed = time.monotonic() - start
        parts = [f"{v} {k}" for k, v in sorted(counts.items())]
        line = f"{prefix}{', '.join(parts)} ({elapsed:.0f}s)"
        if final:
            print(f"\r{line}{'':20}")
        else:
            sys.stdout.write(f"\r{line}...{'':20}")
            sys.stdout.flush()

    for rnd in range(max_rounds):
        # Wall-clock budget check
        elapsed = time.monotonic() - start
        if elapsed > max_wall_seconds:
            logger.warning("Wall-clock budget exceeded: %.0fs > %.0fs", elapsed, max_wall_seconds)
            messages.append(HumanMessage(
                content=(
                    f"[system] Time budget exceeded ({elapsed:.0f}s). "
                    f"Stop using tools and return your final answer now."
                )
            ))
            response = safe_llm_invoke(llm_with_tools, messages, label=label)
            messages.append(response)
            if token_accum is not None:
                usage = extract_token_usage(response)
                token_accum.add(usage)
            break

        # Context budget check
        ctx_chars = _estimate_context_chars(messages)
        if ctx_chars > max_context_chars:
            messages.append(HumanMessage(
                content=(
                    f"[system] Context budget exceeded ({ctx_chars:,} chars). "
                    f"Stop using tools and return your final answer now."
                )
            ))
            response = safe_llm_invoke(llm_with_tools, messages, label=label)
            messages.append(response)
            if token_accum is not None:
                usage = extract_token_usage(response)
                token_accum.add(usage)
            break

        if counts:
            _print_progress()
        response = safe_llm_invoke(llm_with_tools, messages, label=label)
        messages.append(response)

        if token_accum is not None:
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
                # Audit logging (when store is provided)
                if audit_store is not None and audit_issue_id is not None:
                    is_truncated = len(result_str) > 8000
                    audit_store.log_audit(
                        audit_issue_id, audit_branch_id, rnd, tc["name"],
                        tc.get("args", {}), result_str, is_truncated=is_truncated,
                        from_node=audit_from_node,
                    )
                if len(result_str) > 8000:
                    result_str = result_str[:8000] + "\n... (truncated)"
                counts[tc["name"]] = counts.get(tc["name"], 0) + 1
                _print_progress()
                messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))
            else:
                messages.append(ToolMessage(
                    content=f"[error] Unknown tool: {tc['name']}",
                    tool_call_id=tc["id"],
                ))
    if counts:
        _print_progress(final=True)
    return response, messages


def _parse_task_element(task_elem) -> dict:
    """Parse a single <task> XML element into a dict."""
    def _get_text(tag: str) -> str:
        el = task_elem.find(tag)
        return (el.text or "").strip() if el is not None else ""

    def _get_list(tag: str) -> list:
        raw_val = _get_text(tag)
        return [item.strip() for item in raw_val.split(",") if item.strip()] if raw_val else []

    return {
        "branch_id": _get_text("branch_id"),
        "description": _get_text("description"),
        "tools_required": _get_list("tools_required"),
        "skills_required": _get_list("skills_required"),
        "success_criteria": _get_text("success_criteria"),
    }


def _extract_blueprint_xml(raw: str) -> list[dict]:
    """Extract blueprint tasks from XML output.

    Handles code fences, prose preamble, unescaped ampersands, and truncated output.
    Raises ValueError with diagnostics on any parse failure.
    """
    text = raw.strip()

    # Extract XML content from fences or find blueprint tags
    xml_str = None
    _used_fallback_wrap = False
    fence_match = re.search(r"```(?:xml)?\n([\s\S]*?)\n```", text)
    if fence_match:
        xml_str = fence_match.group(1).strip()
    else:
        bp_match = re.search(r"<blueprint>[\s\S]*?</blueprint>", text)
        if bp_match:
            xml_str = bp_match.group(0)
        else:
            xml_str = "<blueprint>" + text + "</blueprint>"
            _used_fallback_wrap = True

    # Fix unescaped ampersands
    xml_str = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;', xml_str)

    try:
        root = ET.fromstring(xml_str)
    except (ET.ParseError, ValueError) as exc:
        original_error = str(exc)
        logger.warning(
            "Blueprint XML parse failed: %s | raw length: %d | first 500 chars: %s",
            original_error, len(raw), raw[:500]
        )
        # Truncation recovery: extract complete <task>...</task> elements
        task_matches = re.findall(r'<task>.*?</task>', xml_str, re.DOTALL)
        if task_matches:
            recovered_xml = re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;)', '&amp;',
                                   '<blueprint>' + ''.join(task_matches) + '</blueprint>')
            try:
                recovered_root = ET.fromstring(recovered_xml)
                tasks = [_parse_task_element(t) for t in recovered_root.findall("task")]
                logger.warning(
                    "Recovered %d complete task(s) from truncated output (original parse failed: %s)",
                    len(tasks), original_error
                )
                return tasks
            except ET.ParseError:
                pass  # Recovery also failed, fall through to raise
        raise ValueError(
            f"Blueprint XML parse failed: {exc} | raw length: {len(raw)} | first 500 chars: {raw[:500]}"
        ) from exc

    tasks = [_parse_task_element(task_elem) for task_elem in root.findall("task")]

    if not tasks and _used_fallback_wrap:
        logger.warning(
            "Blueprint XML parse failed: no <task> elements found in fallback-wrapped input | raw length: %d | first 500 chars: %s",
            len(raw), raw[:500]
        )
        raise ValueError(
            f"Blueprint XML parse failed: no <task> elements found in fallback-wrapped input | "
            f"raw length: {len(raw)} | first 500 chars: {raw[:500]}"
        )
    return tasks


EXPLORE_INSTRUCTION = (
    "Before creating the blueprint, explore the existing codebase to understand its "
    "architecture, key modules, entry points, dependencies, and patterns.\n\n"
    "Use `file_inspect` to inspect important files and `search` to find patterns.\n"
    "Focus on:\n"
    "- Entry points (main files, app factories, route definitions)\n"
    "- Core business logic modules\n"
    "- Data models / schemas\n"
    "- Configuration and dependency files\n"
    "- Existing test structure\n"
    "- **Data files** — note every file extension you encounter (csv, json, pdf, etc.)\n\n"
    "When you have a solid understanding of the codebase, summarize your findings "
    "and then say: EXPLORATION COMPLETE\n\n"
    "Your summary should cover:\n"
    "1. Tech stack and frameworks\n"
    "2. Project structure and key modules\n"
    "3. Current architecture patterns\n"
    "4. Areas relevant to the goals\n"
    "5. **File formats encountered** — list every data/config format the project uses\n"
)

SKILL_PROVISION_INSTRUCTION = (
    "You have just explored the codebase. Now **provision skills** that the "
    "{role_executor} will need.\n\n"
    "## What to Provision\n"
    "Look at the file formats, libraries, and domain patterns you discovered during "
    "exploration and discussion. For each one that does NOT already have a skill, "
    "create one using `skill_create`.\n\n"
    "Common examples:\n"
    "- `.csv` files → create a skill about reading/writing CSVs with pandas\n"
    "- `.json` / `.jsonl` → JSON handling patterns, streaming for large files\n"
    "- `.pdf` → PDF extraction with pymupdf or pdfplumber\n"
    "- `.xlsx` → Excel handling with openpyxl\n"
    "- Image files → PIL/Pillow usage, common transforms\n"
    "- Database files → SQLite patterns, connection handling\n"
    "- API integrations → request patterns, auth, rate limiting\n"
    "- Domain-specific patterns (matching algorithms, data pipelines, etc.)\n\n"
    "## Skill Quality Rules\n"
    "Each skill must be a **concise, actionable guide** — not a textbook chapter. Include:\n"
    "- Which library to use and why (prefer stdlib when possible, name the right third-party lib otherwise)\n"
    "- Installation command (e.g., `uv add pandas`)\n"
    "- 2-3 code patterns covering the most common operations\n"
    "- Gotchas and edge cases specific to that format\n"
    "- Performance tips for large files\n\n"
    "Use your pretrained knowledge — no internet access is needed for standard formats.\n\n"
    "## When to Skip\n"
    "- The format already has an active skill (check the EXISTING SKILLS list)\n"
    "- The format is trivial (plain .txt, .md) — agents already know these\n"
    "- The project doesn't actually use that format in any meaningful way\n\n"
    "Create the skills now, then say: SKILL PROVISIONING COMPLETE"
)

BLUEPRINT_INSTRUCTION = (
    "Based on the goals, discussion, codebase exploration, and any feedback, "
    "produce a Blueprint in XML format.\n\n"
    "Wrap all tasks in a `<blueprint>` root element. Each task is a `<task>` element with these children:\n"
    "- `<branch_id>` (str)\n"
    "- `<description>` (str)\n"
    "- `<tools_required>` (comma-separated: shell,file_write,file_read,file_inspect,search)\n"
    "- `<skills_required>` (comma-separated skill names, or empty)\n"
    "- `<success_criteria>` (str)\n\n"
    "## CRITICAL: Keep Tasks Focused on Core Logic\n"
    "Each task must capture a meaningful **unit of logic or decision** — NOT mechanical steps.\n"
    "- WRONG: \"Load CSV\", \"Write output file\", \"Install dependencies\" — these are obvious boilerplate.\n"
    "- RIGHT: \"Implement pool-based matching by school × has_face\", \"Add mutual gender-preference filter\"\n\n"
    "Think of tasks like drawing a flowchart: you wouldn't draw a box for 'open the file'. "
    "Focus on the filters, algorithms, decision points, and validations that define the system.\n\n"
    "## Branch ID Convention\n"
    "Branch IDs are **hierarchical strings** scoped per-issue:\n"
    "- Root branches: \"1\", \"2\", \"3\"\n"
    "- Sub-branches: \"1.1\", \"1.2\" (children of branch 1)\n"
    "- Deeper: \"1.1.1\" (child of branch 1.1)\n\n"
    "**IMPORTANT:** Branch IDs are unique within each issue. Different issues can reuse the same IDs.\n"
    "When you see the EXISTING TASK TREE, note the [Issue #N] prefix — only avoid collisions within the CURRENT issue.\n\n"
    "If an EXISTING TASK TREE is provided below, assign IDs that reflect relationships:\n"
    "- New work extending existing branch \"2\" on the current issue → use \"2.1\", \"2.2\"\n"
    "- Completely new, unrelated work → use the next unused root ID for this issue\n\n"
    "If NO existing tasks exist for the current issue, start from \"1\".\n\n"
    "## Skills\n"
    "If AVAILABLE SKILLS are listed below, assign relevant skill names to each task's "
    "`skills_required` element. Only assign skills genuinely useful for the task. "
    "If no skill fits, leave the element empty.\n\n"
    "Return ONLY the XML blueprint, no other text."
)

FLOWCHART_INSTRUCTION = (
    "Produce a **high-level architecture diagram** of the user's project in Mermaid syntax.\n\n"
    "## Purpose\n"
    "This diagram helps the user (and their team) understand the project at a glance.\n"
    "If they show it to their boss, the boss should get the big picture in 30 seconds.\n\n"
    "## Hard Constraints\n"
    "- **Max 12 nodes.** If you need more, you're too detailed.\n"
    "- Use `flowchart TD`.\n"
    "- Each node = a **component, data source, module, or key algorithm** in the project.\n"
    "- Edges = data flow or dependencies between components.\n\n"
    "## INCLUDE (what a stakeholder cares about)\n"
    "- Major modules / services and how they connect\n"
    "- Data sources (databases, APIs, files) and where data flows\n"
    "- Core algorithms or processing stages\n"
    "- Key outputs (reports, APIs, files)\n\n"
    "## DO NOT INCLUDE\n"
    "- TMB's own workflow (planning steps, task sequence, validation)\n"
    "- Implementation details (file I/O, imports, error handling)\n"
    "- Per-field or per-column details\n"
    "- Setup, install, or teardown steps\n\n"
    "Think: project architecture poster on the team wall.\n\n"
    "Return ONLY the Mermaid code block (```mermaid ... ```), no other text."
)


FLOWCHART_NEEDED_INSTRUCTION = (
    "Based on the goals and blueprint, does this project have meaningful architecture "
    "worth diagramming for the user? Answer with ONLY 'yes' or 'no'.\n\n"
    "Say 'yes' if: multiple components, data pipelines, algorithms, or services.\n"
    "Say 'no' if: single script, simple task, documentation-only, or no real architecture.\n"
)

def _maybe_generate_flowchart(
    llm, system_prompt, objective, blueprint,
    exploration_summary, issue_id, store, token_accum, planner_display,
    *, force: bool = False,
):
    """Ask the Planner whether a flowchart is warranted, then generate if yes."""
    if not force:
        decide_parts = [
            f"## Goals\n{objective}",
            f"## Blueprint ({len(blueprint)} tasks)\n```json\n{json.dumps(blueprint[:5], indent=2)}\n```",
            FLOWCHART_NEEDED_INSTRUCTION,
        ]
        decide_resp = safe_llm_invoke(llm, [
            SystemMessage(content=system_prompt),
            HumanMessage(content="\n\n".join(decide_parts)),
        ])
        usage = extract_token_usage(decide_resp)
        token_accum.add(usage)
        answer = _normalize_content(decide_resp.content).strip().lower()

        if "no" in answer and "yes" not in answer:
            store.log(issue_id, None, "planner", "flowchart_skipped", {},
                      summary="Planner decided flowchart not needed")
            print(f"[{planner_display}] Flowchart skipped (simple project).")
            return

    print(f"[{planner_display}] 🗺️ Generating project architecture flowchart...")
    fc_parts = [
        f"## Goals\n{objective}",
        f"## Blueprint\n```json\n{json.dumps(blueprint, indent=2)}\n```",
    ]
    if exploration_summary:
        fc_parts.append(f"## Codebase Understanding\n{exploration_summary}")
    fc_parts.append(FLOWCHART_INSTRUCTION)

    fc_messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(fc_parts)),
    ]
    fc_response = safe_llm_invoke(llm, fc_messages)
    usage = extract_token_usage(fc_response)
    token_accum.add(usage)
    fc_raw = _normalize_content(fc_response.content)

    if "mermaid" not in fc_raw.lower() and len(fc_raw) < 200:
        print(f"[{planner_display}] Flowchart too short, retrying...")
        fc_response = safe_llm_invoke(llm, fc_messages)
        usage = extract_token_usage(fc_response)
        token_accum.add(usage)
        fc_raw = _normalize_content(fc_response.content)

    flowchart_md = (
        f"# Project Architecture — Issue #{issue_id}\n\n"
        f"**Objective**: {objective[:120]}\n\n"
        f"{fc_raw}\n"
    )
    _write_doc("FLOWCHART.md", flowchart_md)
    store.log(issue_id, None, "planner", "flowchart_generated", {},
              summary="Generated FLOWCHART.md (project architecture)")
    print(f"[{planner_display}] 🗺️ Flowchart saved → {docs_dir().name}/FLOWCHART.md")


def _maybe_update_flowchart_after_task(
    llm, system_prompt, state, task, verdict_text,
    issue_id, store, planner_display,
):
    """After a PASS, check if the completed task changed architecture enough to update the flowchart."""
    check_prompt = (
        f"Task [{task['branch_id']}] just passed validation.\n"
        f"Description: {task.get('description', '')[:200]}\n"
        f"Verdict: {verdict_text[:300]}\n\n"
        "Did this task introduce a **significant architectural change** to the project "
        "(new module, changed data flow, restructured pipeline, new service)?\n"
        "Answer ONLY 'yes' or 'no'."
    )
    resp = safe_llm_invoke(llm, [
        SystemMessage(content=system_prompt),
        HumanMessage(content=check_prompt),
    ])
    answer = _normalize_content(resp.content).strip().lower()

    if "yes" in answer and "no" not in answer:
        print(f"[{planner_display}] 🗺️ Significant change detected — updating flowchart...")
        token_accum = TokenAccumulator()
        _maybe_generate_flowchart(
            llm, system_prompt,
            state.get("objective", ""),
            state.get("blueprint", []),
            state.get("project_context", ""),
            issue_id, store, token_accum, planner_display,
            force=True,
        )
        store.log_tokens(issue_id, "planner", token_accum.input_tokens, token_accum.output_tokens)


def _per_task_exec_instruction():
    return (
        f"The {get_role_name('owner')} has approved the blueprint. "
        "Write a concise execution plan for THIS SINGLE TASK.\n\n"
        "## Rules\n"
        "- You provide the **roadmap** — the Executor writes the code.\n"
        "- Do NOT include full source code or complete scripts.\n"
        "- DO include: key decisions, algorithm outlines, file paths, commands to run, expected outputs.\n"
        "- Keep it under 40 lines. Focus on what a competent developer needs to know, not what they already know.\n\n"
        "## Format\n"
        "```\n"
        "### Steps\n"
        "1. ...\n"
        "2. ...\n\n"
        "### Key Decisions\n"
        "- ...\n\n"
        "### Expected Output\n"
        "- ...\n"
        "```\n\n"
        "Return ONLY the Markdown for this one task."
    )


def planner_plan(state: AgentState) -> dict:
    """Explore codebase, then generate BLUEPRINT.md and FLOWCHART.md."""
    try:
        return _planner_plan_impl(state)
    except LLMConnectionError as e:
        planner_display = get_role_name("planner").upper()
        print(f"\n[{planner_display}] ❌ LLM connection error:\n{e}\n")
        store = Store()
        issue_id = state.get("issue_id")
        store.log(issue_id, None, "planner", "llm_connection_error", {
            "error": str(e)[:500],
        }, summary=f"LLM connection error: {str(e)[:100]}")
        return {"blueprint": [], "next_node": "__end__"}


def _planner_plan_impl(state: AgentState) -> dict:
    """Inner implementation of planner_plan — may raise LLMConnectionError."""
    node_cfg = load_nodes_config().get("planner", {})
    project_cfg = load_project_config()
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
    token_accum = TokenAccumulator()

    is_replan = bool(feedback)

    # ── 0. Explore the codebase ──────────────────────────────
    exploration_summary = ""
    if tools and not is_replan:
        print(f"[{planner_display}] 🔍 Exploring codebase...")
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
            label="explore", token_accum=token_accum,
        )
        exploration_summary = _normalize_content(explore_response.content)

        if len(exploration_summary) < 300:
            explore_messages.append(HumanMessage(content=(
                "Your summary is too brief. Provide a detailed summary (at least 300 chars) covering:\n"
                "1. Tech stack and frameworks\n"
                "2. Project structure and key modules\n"
                "3. Architecture patterns relevant to the goals\n"
                "4. File formats and data files\n\n"
                "Summarize what you learned from the files you inspected."
            )))
            summary_resp = safe_llm_invoke(llm, explore_messages)
            usage = extract_token_usage(summary_resp)
            token_accum.add(usage)
            exploration_summary = _normalize_content(summary_resp.content)

        store.log(issue_id, None, "planner", "codebase_explored", {
            "summary_length": len(exploration_summary),
        }, summary="Explored codebase structure and key modules")
        print(f"[{planner_display}] 🔍 Exploration complete ({len(exploration_summary)} chars)")
    elif is_replan:
        print(f"[{planner_display}] 🔄 Re-planning based on feedback...")
    else:
        print(f"[{planner_display}] 📋 Building blueprint from discussion...")

    # ── 0a. Skill provisioning ────────────────────────────────
    if tools and not is_replan:
        available_skills = store.get_all_skills()
        existing_names = {s["name"] for s in available_skills}
        skill_section = ""
        if existing_names:
            skill_section = (
                "\n\n## Existing Skills (do NOT recreate these)\n"
                + "\n".join(f"- {n}" for n in sorted(existing_names))
            )

        provision_prompt = SKILL_PROVISION_INSTRUCTION.format(
            role_executor=get_role_name("executor"),
        )
        provision_parts = []
        if exploration_summary:
            provision_parts.append(f"## Codebase Exploration Summary\n{exploration_summary}")
        if discussion:
            provision_parts.append(f"## Discussion with {owner_display}\n{discussion}")
        provision_parts.append(f"## Goals\n{objective}")
        if skill_section:
            provision_parts.append(skill_section)
        provision_parts.append(provision_prompt)

        provision_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content="\n\n".join(provision_parts)),
        ]

        print(f"[{planner_display}] 🧠 Provisioning skills for downstream agents...")
        _run_tool_loop(
            llm_with_tools, provision_messages, tool_map, _MAX_EXPLORE_ROUNDS, label="skill-provisioning",
            token_accum=token_accum,
            audit_store=store, audit_issue_id=issue_id,
        )

        new_skills = store.get_all_skills()
        created_count = len(new_skills) - len(available_skills)
        if created_count > 0:
            skill_names = [s["name"] for s in new_skills if s["name"] not in existing_names]
            store.log(issue_id, None, "planner", "skills_provisioned", {
                "created": skill_names,
            }, summary=f"Auto-provisioned {created_count} skill(s): {', '.join(skill_names)}")
            print(f"[{planner_display}] ✅ Created {created_count} skill(s): {', '.join(skill_names)}")
        else:
            print(f"[{planner_display}] No new skills needed.")

    # ── 0b. Handle pending skill requests ──────────────────────
    pending_requests = store.get_pending_skill_requests()
    if pending_requests:
        print(f"[{planner_display}] Handling {len(pending_requests)} skill request(s)...")
        for req in pending_requests:
            matches = store.search_skills(req["need"])
            if matches:
                best = matches[0]
                store.resolve_skill_request(
                    req["id"], resolved_skill=best["name"],
                    resolution_note=f"Matched existing skill: {best['name']}",
                )
                store.log(issue_id, None, "planner", "skill_request_matched", {
                    "request_id": req["id"], "need": req["need"][:200],
                    "matched_skill": best["name"],
                }, summary=f"Skill request matched → {best['name']}")
                print(f"  [{planner_display}] Request '{truncate(req['need'], 60)}' → existing skill: {best['name']}")
            elif tools:
                create_prompt = (
                    f"An agent ({req['requested_by']}) requested a skill:\n\n"
                    f"**Need**: {req['need']}\n"
                    f"**Context**: {req.get('context', '(none)')}\n\n"
                    "Create this skill using `skill_create`. Write a concise, actionable guide "
                    "based on your pretrained knowledge. Include:\n"
                    "- Which library to use and installation command\n"
                    "- 2-3 code patterns for common operations\n"
                    "- Gotchas and edge cases\n\n"
                    "After creating the skill, say: DONE"
                )
                create_msgs = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=create_prompt),
                ]
                _run_tool_loop(llm_with_tools, create_msgs, tool_map, 5, token_accum=token_accum)
                new_skill = store.search_skills(req["need"])
                skill_name = new_skill[0]["name"] if new_skill else None
                store.resolve_skill_request(
                    req["id"], resolved_skill=skill_name,
                    resolution_note="Created by planner",
                    status="fulfilled" if skill_name else "pending",
                )
                if skill_name:
                    store.log(issue_id, None, "planner", "skill_request_fulfilled", {
                        "request_id": req["id"], "skill": skill_name,
                    }, summary=f"Created skill for request: {skill_name}")
                    print(f"  [{planner_display}] Created skill '{skill_name}' for request")
            else:
                print(f"  [{planner_display}] No tools to create skill for: {truncate(req['need'], 60)}")

    # ── 0c. Review pending skills ─────────────────────────────
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
            skill_path = _resolve_skill_path(ps.get("file_path", ""))
            if skill_path:
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
            review_resp = safe_llm_invoke(llm, review_msgs)
            usage = extract_token_usage(review_resp)
            token_accum.add(usage)
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
        tree_lines = [
            f"- **[Issue #{t['issue_id']}] {t['branch_id']}**: {t['title']} [{t['status']}]"
            for t in existing_tree
        ]
        parts.append("## Existing Task Tree\n" + "\n".join(tree_lines))
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

    print(f"[{planner_display}] 📋 Generating blueprint...")
    response, messages = _run_tool_loop(
        llm_with_tools, messages, tool_map, 5, label="blueprint",
        token_accum=token_accum,
        audit_store=store, audit_issue_id=issue_id,
    )
    raw = _normalize_content(response.content)

    blueprint = []
    try:
        blueprint = _extract_blueprint_xml(raw)
    except ValueError as exc:
        logger.warning("First blueprint parse attempt failed: %s", exc)

    if not blueprint:
        messages.append(HumanMessage(content=(
            "You have finished exploring. Now output the blueprint.\n\n"
            "Return ONLY XML — no prose, no markdown fences, no explanation.\n"
            "Use this format:\n"
            "<blueprint>\n"
            "  <task>\n"
            "    <branch_id>1</branch_id>\n"
            "    <description>...</description>\n"
            "    <tools_required>shell,file_write</tools_required>\n"
            "    <skills_required></skills_required>\n"
            "    <success_criteria>...</success_criteria>\n"
            "  </task>\n"
            "</blueprint>"
        )))
        retry_resp = safe_llm_invoke(llm, messages)
        usage = extract_token_usage(retry_resp)
        token_accum.add(usage)
        raw = _normalize_content(retry_resp.content)
        try:
            blueprint = _extract_blueprint_xml(raw)
        except ValueError as exc:
            logger.warning("Blueprint retry parse also failed: %s", exc)
            print(f"[{planner_display}] ⚠️ Failed to parse blueprint XML. Raw response ({len(raw)} chars):")
            print(raw[:300])
            blueprint = []

    store.create_tasks(issue_id, blueprint)
    if is_replan:
        store.log(issue_id, None, "planner", "blueprint_revised", {
            "reason": feedback[:500],
            "task_count": len(blueprint),
        }, summary=f"Blueprint revised: {len(blueprint)} tasks")

    blueprint_md = store.export_blueprint_md(issue_id, blueprint)
    _write_doc("BLUEPRINT.md", blueprint_md)
    print(f"[{planner_display}] 📋 Blueprint saved → {docs_dir().name}/BLUEPRINT.md ({len(blueprint)} tasks)")

    # ── 2. Conditionally Generate Flowchart ─────────────────
    if not blueprint:
        replan_count = state.get("replan_count", 0) + 1
        max_replans = project_cfg.get("max_replan_attempts", 3)
        print(f"[{planner_display}] ⚠️ No blueprint was generated (attempt {replan_count}/{max_replans}).")
        store.log_tokens(issue_id, "planner", token_accum.input_tokens, token_accum.output_tokens)
        if replan_count >= max_replans:
            store.log(issue_id, None, "planner", "replan_limit_reached", {
                "attempts": replan_count,
            }, summary=f"Re-plan limit reached after {replan_count} attempts")
            print(f"[{planner_display}] ❌ Re-plan limit reached. Aborting.")
            return {
                "blueprint": [],
                "next_node": "__end__",
                "replan_count": replan_count,
            }
        return {
            "blueprint": [],
            "next_node": "planner",
            "replan_count": replan_count,
            "review_feedback": "Blueprint was empty — planner should retry.",
        }

    _maybe_generate_flowchart(
        llm, system_prompt, objective, blueprint,
        exploration_summary, issue_id, store, token_accum, planner_display,
    )

    print(f"[{planner_display}] ✅ Planning complete: {len(blueprint)} tasks")
    store.log_tokens(issue_id, "planner", token_accum.input_tokens, token_accum.output_tokens)

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
        "2. Use `shell` to run scripts, tests, or commands to diagnose issues.\n"
        "3. Use `file_write` to make changes directly.\n"
        "4. Use `shell` again to verify your fix works.\n\n"
        "When done, provide a short summary of what you found and changed."
    )


def planner_quick_task(instruction: str, project_context: str, issue_id: int):
    """Planner handles a simple task directly — no graph, no executor."""
    try:
        return _planner_quick_task_impl(instruction, project_context, issue_id)
    except LLMConnectionError as e:
        planner_display = get_role_name("planner").upper()
        print(f"\n[{planner_display}] ❌ LLM connection error:\n{e}\n")
        Store().log(issue_id, None, "planner", "llm_connection_error", {
            "error": str(e)[:500],
        }, summary=f"LLM connection error: {str(e)[:100]}")
        return f"Error: {e}"


def _planner_quick_task_impl(instruction: str, project_context: str, issue_id: int):
    """Inner implementation — may raise LLMConnectionError."""
    node_cfg = load_nodes_config().get("planner", {})
    project_root = str(get_project_root())
    llm = get_llm("planner")
    system_prompt = load_prompt("planner")
    store = Store()

    quick_tools_names = list(set(
        node_cfg.get("tools", []) + ["file_read", "file_write", "shell"]
    ))
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
    token_accum = TokenAccumulator()
    response, messages = _run_tool_loop(
        llm_with_tools, messages, tool_map, _MAX_EXPLORE_ROUNDS,
        token_accum=token_accum,
    )
    result = _normalize_content(response.content)

    store.log_tokens(issue_id, "planner", token_accum.input_tokens, token_accum.output_tokens)
    store.log(issue_id, None, "planner", "quick_task_completed", {},
             summary=f"Quick: {instruction[:150]}")
    print(f"[{planner_display}] Done.")
    return result


def _evolve_plan_instruction():
    return (
        "You are in **self-evolution mode**. You are modifying the TMB framework itself.\n\n"
        f"The {get_role_name('owner')} has given you an instruction to improve or change the TMB engine.\n"
        "You have full read access to TMB's own source code.\n\n"
        "Steps:\n"
        "1. Use `file_read` and `search` to explore the TMB codebase.\n"
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


def planner_evolve(instruction: str, tmb_context: str, issue_id: int) -> str:
    """Exploration + plan phase of self-evolution. Returns the plan markdown.

    Runs inside evolve_context() — TMB/** blacklist is lifted for reads.
    """
    node_cfg = load_nodes_config().get("evolve", load_nodes_config().get("planner", {}))
    llm = get_llm("planner")
    system_prompt = load_prompt("planner")
    store = Store()

    tmb_root_str = str(TMB_ROOT)
    tool_names = ["file_read", "search"]
    tools = get_tools_for_node(tool_names, tmb_root_str, node_name="planner")
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    parts = []
    if tmb_context:
        parts.append(f"## TMB Codebase Context\n{tmb_context}")
    parts.append(f"## Instruction\n{instruction}")
    parts.append(_evolve_plan_instruction())

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content="\n\n".join(parts)),
    ]

    planner_display = get_role_name("planner").upper()
    print(f"[{planner_display}] Exploring TMB codebase for evolution plan...")
    token_accum = TokenAccumulator()
    response, messages = _run_tool_loop(
        llm_with_tools, messages, tool_map, _MAX_EXPLORE_ROUNDS,
        token_accum=token_accum,
    )
    plan = _normalize_content(response.content)

    store.log_tokens(issue_id, "planner", token_accum.input_tokens, token_accum.output_tokens)
    _write_doc("EVOLUTION.md", plan)
    store.log(issue_id, None, "planner", "evolve_plan_generated", {
        "instruction": instruction[:300],
    }, summary=f"Evolution plan: {instruction[:120]}")

    print(f"[{planner_display}] Evolution plan saved to {docs_dir().name}/EVOLUTION.md")
    return plan


def planner_evolve_execute(
    instruction: str, plan: str, tmb_context: str, issue_id: int,
) -> str:
    """Execution phase of self-evolution. Applies the approved plan.

    Runs inside evolve_context() — full TMB read/write access.
    """
    node_cfg = load_nodes_config().get("evolve", load_nodes_config().get("planner", {}))
    llm = get_llm("planner")
    system_prompt = load_prompt("planner")
    store = Store()

    tmb_root_str = str(TMB_ROOT)
    tool_names = list(set(
        node_cfg.get("tools", ["file_read", "search"]) + ["file_write", "shell"]
    ))
    tools = get_tools_for_node(tool_names, tmb_root_str, node_name="planner")
    tool_map = {t.name: t for t in tools}
    llm_with_tools = llm.bind_tools(tools)

    parts = [
        f"## TMB Codebase Context\n{tmb_context}" if tmb_context else "",
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
    token_accum = TokenAccumulator()
    response, messages = _run_tool_loop(
        llm_with_tools, messages, tool_map, 15,
        token_accum=token_accum,
    )
    result = _normalize_content(response.content)

    store.log_tokens(issue_id, "planner", token_accum.input_tokens, token_accum.output_tokens)
    store.log(issue_id, None, "planner", "evolve_executed", {
        "instruction": instruction[:300],
    }, summary=f"Executed evolution: {instruction[:120]}")

    print(f"[{planner_display}] Evolution execution complete.")
    return result


def planner_execution_plan(state: AgentState) -> dict:
    """Generate per-task execution plans and store each in SQLite."""
    try:
        return _planner_execution_plan_impl(state)
    except LLMConnectionError as e:
        planner_display = get_role_name("planner").upper()
        print(f"\n[{planner_display}] ❌ LLM connection error:\n{e}\n")
        store = Store()
        issue_id = state.get("issue_id")
        store.log(issue_id, None, "planner", "llm_connection_error", {
            "error": str(e)[:500],
        }, summary=f"LLM connection error: {str(e)[:100]}")
        return {"next_node": "__end__"}


def _planner_execution_plan_impl(state: AgentState) -> dict:
    """Inner implementation — may raise LLMConnectionError.

    Loops over blueprint tasks, generating a concise plan for each one
    individually. Writes a lightweight summary to doc/EXECUTION.md for
    human review.
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

    total = len(blueprint)
    print(f"[{planner_display}] 📝 Generating execution plans for {total} tasks...")

    summary_lines = [
        f"# Execution Plan — Issue #{issue_id}\n",
        f"**Objective**: {objective[:120]}\n",
        f"---\n",
    ]

    last_response = None
    token_accum = TokenAccumulator()
    for i, task in enumerate(blueprint):
        branch_id = task["branch_id"]
        description = task.get("description", "")
        success_criteria = task.get("success_criteria", "")
        skills = task.get("skills_required", [])
        title = truncate(description, 80)

        existing_plan = store.get_task_execution_plan(issue_id, branch_id)
        if existing_plan:
            print(f"  [{branch_id}] already has plan, skipping")
            summary_lines.append(f"## Task {branch_id}\n{truncate(description, 120)}\n")
            continue

        parts = []
        if project_context:
            parts.append(f"## Project Context (summary)\n{project_context[:1000]}")
        parts.append(f"## Goal\n{objective[:300]}")
        parts.append(
            f"## Current Task ({i+1}/{total})\n"
            f"**Branch ID**: {branch_id}\n"
            f"**Description**: {description}\n"
            f"**Success Criteria**: {success_criteria}\n"
            f"**Skills**: {', '.join(skills) if skills else 'none'}"
        )
        if i > 0:
            prev_titles = [f"- [{t['branch_id']}] {truncate(t.get('description', ''), 60)}" for t in blueprint[:i]]
            parts.append(f"## Previous Tasks (already planned)\n" + "\n".join(prev_titles))
        parts.append(_per_task_exec_instruction())

        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content="\n\n".join(parts)),
        ]

        print(f"  [{branch_id}] planning ({i+1}/{total})...")
        response, messages = _run_tool_loop(
            llm_with_tools, messages, tool_map, 5, label=f"task-{branch_id}",
            token_accum=token_accum,
            audit_store=store, audit_issue_id=issue_id, audit_branch_id=branch_id,
        )
        plan_md = _normalize_content(response.content)
        last_response = response

        store.update_task_execution_plan(issue_id, branch_id, plan_md)
        store.log(issue_id, branch_id, "planner", "task_plan_generated", {
            "chars": len(plan_md),
        }, summary=f"Execution plan for [{branch_id}]: {title}")

        summary_lines.append(f"## Task {branch_id}\n{truncate(description, 120)}\n")

    store.log_tokens(issue_id, "planner", token_accum.input_tokens, token_accum.output_tokens)
    summary_md = "\n".join(summary_lines) + "\n"
    _write_doc("EXECUTION.md", summary_md)
    store.log(issue_id, None, "planner", "execution_plan_generated", {
        "task_count": total,
    }, summary=f"Generated per-task execution plans for {total} tasks")
    print(f"[{planner_display}] ✅ Execution plans stored. Summary → {docs_dir().name}/EXECUTION.md")

    return {
        "messages": state.get("messages", []) + ([last_response] if last_response else []),
        "next_node": "executor",
    }


# ── Validation helpers ────────────────────────────────────────


def _extract_verdict_xml(text: str) -> bool:
    """Determine PASS/FAIL from validation output using XML tags.

    Strategy (in priority order):
      1. XML <verdict> tag
      2. Keyword fallback — last keyword wins
      3. Fail-closed default: False
    """
    # Tier 1: XML <verdict> tag
    xml_match = re.search(r"<verdict>\s*(PASS|FAIL)\s*</verdict>", text, re.IGNORECASE)
    if xml_match:
        return xml_match.group(1).upper() == "PASS"

    # Tier 2: keyword fallback — last occurrence wins
    pass_match = re.search(r"\bPASS\b", text, re.IGNORECASE)
    fail_match = re.search(r"\bFAIL\b", text, re.IGNORECASE)
    if pass_match and not fail_match:
        result = True
        logger.warning(
            "Verdict fell back to keyword match (%s) — no <verdict> tag found | first 200 chars: %s",
            "PASS" if result else "FAIL", text[:200]
        )
        return result
    if fail_match and not pass_match:
        result = False
        logger.warning(
            "Verdict fell back to keyword match (%s) — no <verdict> tag found | first 200 chars: %s",
            "PASS" if result else "FAIL", text[:200]
        )
        return result
    if pass_match and fail_match:
        # Last one wins
        result = pass_match.start() > fail_match.start()
        logger.warning(
            "Verdict fell back to keyword match (%s) — no <verdict> tag found | first 200 chars: %s",
            "PASS" if result else "FAIL", text[:200]
        )
        return result

    # Tier 3: fail-closed default
    logger.warning(
        "No verdict extracted — defaulting to FAIL (fail-closed) | text length: %d | first 200 chars: %s",
        len(text), text[:200]
    )
    return False


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


def _record_skill_outcomes(store: Store, skill_names: list[str], is_pass: bool):
    """Update effectiveness counters for every skill used in this task."""
    for name in skill_names:
        msg = store.record_skill_outcome(name, is_pass)
        if msg:
            print(f"[{get_role_name('planner').upper()}] {msg}")


# ── Planner Validate ─────────────────────────────────────────


def planner_validate(state: AgentState) -> dict:
    """Validate executor output against success criteria."""
    try:
        return _planner_validate_impl(state)
    except LLMConnectionError as e:
        planner_display = get_role_name("planner").upper()
        print(f"\n[{planner_display}] ❌ LLM connection error:\n{e}\n")
        store = Store()
        issue_id = state.get("issue_id")
        store.log(issue_id, None, "planner", "llm_connection_error", {
            "error": str(e)[:500],
        }, summary=f"LLM connection error: {str(e)[:100]}")
        return {"next_node": "__end__"}


def _planner_validate_impl(state: AgentState) -> dict:
    """Inner implementation — may raise LLMConnectionError.

    The Planner validates because it already holds full context — data
    schema, algorithm design, success criteria, edge cases.  No context
    re-learning needed.
    """
    node_cfg = load_nodes_config().get("planner", {})
    project_root = str(get_project_root())
    llm = get_llm("planner")
    system_prompt = load_prompt("planner")
    project_cfg = load_project_config()
    max_retries = project_cfg.get("max_retry_per_task", 3)
    store = Store()
    issue_id = state.get("issue_id")

    validate_tools = ["shell", "file_inspect", "search"]
    tools = get_tools_for_node(validate_tools, project_root, node_name="planner")
    tool_map = {t.name: t for t in tools} if tools else {}
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    blueprint = state["blueprint"]
    idx = state["current_task_idx"]
    task = blueprint[idx]
    branch_id = task["branch_id"]
    total = len(blueprint)
    execution_log = state.get("execution_log", "")
    iteration_count = state.get("iteration_count", 0)

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

    planner_display = get_role_name("planner").upper()
    print(f"[{planner_display}] 🧪 [{branch_id}] validating ({idx+1}/{total})...")

    verify_prompt = (
        f"## Validation Task\n"
        f"You are now **validating** the Executor's work on task [{branch_id}].\n\n"
        f"**Success criteria**: {task['success_criteria']}\n\n"
    )
    if skills_text:
        verify_prompt += f"## Reference Skills\n{skills_text}\n\n"
    verify_prompt += (
        f"## Executor's Log\n{execution_log}\n\n"
        "## Instructions\n"
        "### Step 1: Scan the Executor's Log\n"
        "Read the ENTIRE executor log above carefully. Look for:\n"
        "- **Errors**: exceptions, tracebacks, non-zero exit codes, failed commands\n"
        "- **Warnings**: deprecation notices, resource warnings, missing optional dependencies\n"
        "- **Repeated failures**: the same error appearing multiple times (loop pattern)\n\n"
        "If the executor's log contains unaddressed errors or warnings, FAIL the task — even if "
        "the final output looks correct. The executor must handle warnings, not ignore them.\n\n"
        "### Step 2: Discover and Run Tests\n"
        "Detect the project's test framework by checking for these files:\n"
        "- `pyproject.toml` or `setup.py` → try `python -m pytest` or `uv run pytest`\n"
        "- `package.json` → try `npm test`\n"
        "- `Cargo.toml` → try `cargo test`\n"
        "- `go.mod` → try `go test ./...`\n"
        "- `Makefile` with test target → try `make test`\n"
        "- `build.gradle` or `pom.xml` → try `./gradlew test` or `mvn test`\n\n"
        "Use `shell` to check which build files exist, then run the appropriate test command. "
        "If no test framework is detected, skip this step.\n\n"
        "### Step 3: Verify Success Criteria\n"
        "Use `shell`, `file_inspect`, or `search` to verify each success criterion.\n\n"
        "### Step 4: Render Verdict\n"
        "Use XML tags:\n\n"
        "<verdict>PASS</verdict> or <verdict>FAIL</verdict>\n"
        "<evidence>what you verified, test results, and any warnings found</evidence>\n"
        "<failure_details>specific actionable feedback if FAIL</failure_details>\n\n"
        "FAIL if: errors in log, tests fail, unaddressed warnings, or success criteria not met.\n"
        "PASS only if: log is clean, tests pass (if applicable), and all criteria met."
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=verify_prompt),
    ]

    token_accum = TokenAccumulator()
    response, messages = _run_tool_loop(
        llm_with_tools, messages, tool_map, 10, label=f"validate-{branch_id}",
        token_accum=token_accum,
        audit_store=store, audit_issue_id=issue_id, audit_branch_id=branch_id,
    )
    store.log_tokens(issue_id, "planner", token_accum.input_tokens, token_accum.output_tokens)

    verdict_text = _normalize_content(response.content)
    is_pass = _extract_verdict_xml(verdict_text)

    _record_skill_outcomes(store, skill_names, is_pass)

    if is_pass:
        next_idx = idx + 1
        is_done = next_idx >= len(blueprint)

        store.update_task_status(issue_id, branch_id, "completed")
        store.archive_task_qa_results(issue_id, branch_id, verdict_text[:2000])
        store.log(issue_id, branch_id, "planner", "verdict_pass", {
            "evidence": verdict_text[:1000],
        }, summary=f"PASS: [{branch_id}]")

        print(f"[{planner_display}] ✅ [{branch_id}] — PASS")

        blueprint_md = store.export_blueprint_md(issue_id)
        _write_doc("BLUEPRINT.md", blueprint_md)

        if store.has_event(issue_id, "flowchart_generated"):
            _maybe_update_flowchart_after_task(
                llm, system_prompt, state, task, verdict_text,
                issue_id, store, planner_display,
            )

        if is_done:
            print(f"\n[{planner_display}] 🎉 All {total} tasks passed!")

        return {
            "current_task_idx": next_idx,
            "iteration_count": 0,
            "review_feedback": "",
            "execution_log": "",
            "messages": state.get("messages", []) + [response],
            "next_node": "__end__" if is_done else "executor",
        }

    new_iteration = iteration_count + 1

    store.log(issue_id, branch_id, "planner", "verdict_fail", {
        "attempt": new_iteration,
        "max_retries": max_retries,
        "feedback": verdict_text[:1000],
    }, summary=f"FAIL: [{branch_id}] (attempt {new_iteration}/{max_retries})")

    if new_iteration >= max_retries:
        store.update_task_status(issue_id, branch_id, "failed")
        store.log(issue_id, branch_id, "planner", "max_retries_exceeded", {
            "attempts": new_iteration,
        }, summary=f"Max retries hit for [{branch_id}]")
        print(f"[{planner_display}] ❌ [{branch_id}] — FAIL (attempt {new_iteration}/{max_retries}, escalating)")
        return {
            "iteration_count": new_iteration,
            "review_feedback": f"Max retries ({max_retries}) exceeded. Feedback:\n{verdict_text}",
            "messages": state.get("messages", []) + [response],
            "next_node": "__end__",
        }

    print(f"[{planner_display}] 🔄 [{branch_id}] — FAIL (attempt {new_iteration}/{max_retries}, retrying)")
    return {
        "iteration_count": new_iteration,
        "review_feedback": verdict_text,
        "messages": state.get("messages", []) + [response],
        "next_node": "executor",
    }
