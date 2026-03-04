"""Architect node — produces the blueprint from goals + discussion."""

from __future__ import annotations

import json

from langchain_core.messages import SystemMessage, HumanMessage

from aide.config import get_llm, load_prompt, _AIDE_ROOT
from aide.permissions import assert_aide_write
from aide.state import AgentState


BLUEPRINT_INSTRUCTION = (
    "Based on the goals, discussion, and any feedback, produce a Blueprint as a JSON array. "
    "Each element must have: task_id (int), description (str), tools_required (list[str]), "
    "success_criteria (str). Return ONLY the JSON array, no other text."
)


def architect(state: AgentState) -> dict:
    llm = get_llm("architect")
    system_prompt = load_prompt("architect")
    store = state.get("store")
    issue_id = state.get("issue_id")

    messages = [SystemMessage(content=system_prompt)]

    objective = state["objective"]
    feedback = state.get("review_feedback", "")
    escalation_log = state.get("execution_log", "")
    project_context = state.get("project_context", "")
    discussion = state.get("discussion", "")

    is_replan = bool(feedback)

    if is_replan:
        print("[ARCHITECT] Re-planning based on feedback...")
    else:
        print("[ARCHITECT] Building blueprint from discussion...")

    parts = []
    if project_context:
        parts.append(f"## Project Context\n{project_context}")
    parts.append(f"## Goals\n{objective}")
    if discussion:
        parts.append(f"## Discussion with CTO\n{discussion}")
    if feedback:
        parts.append(f"## Previous Feedback / Escalation\n{feedback}")
    if escalation_log:
        parts.append(f"## Execution Log\n{escalation_log}")
    parts.append(BLUEPRINT_INSTRUCTION)

    user_content = "\n\n".join(parts)
    messages.append(HumanMessage(content=user_content))

    response = llm.invoke(messages)
    raw = response.content

    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        blueprint = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        blueprint = []

    if store and issue_id:
        store.create_tasks(issue_id, blueprint)
        event = "blueprint_revised" if is_replan else "blueprint_created"
        if is_replan:
            store.log(issue_id, None, "architect", event, {
                "reason": feedback[:500],
                "task_count": len(blueprint),
            })

        blueprint_md = store.export_blueprint_md(issue_id, blueprint)
        doc_dir = _AIDE_ROOT / "doc"
        doc_dir.mkdir(parents=True, exist_ok=True)
        blueprint_path = doc_dir / "BLUEPRINT.md"
        assert_aide_write(blueprint_path)
        blueprint_path.write_text(blueprint_md)
        print(f"[ARCHITECT] Blueprint saved to doc/BLUEPRINT.md")

    print(f"[ARCHITECT] Blueprint: {len(blueprint)} tasks")

    return {
        "blueprint": blueprint,
        "current_task_idx": 0,
        "iteration_count": 0,
        "review_feedback": "",
        "execution_log": "",
        "messages": state.get("messages", []) + [response],
        "next_node": "human_review",
    }
