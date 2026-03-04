"""Architect node — plans the blueprint from the CTO's objective."""

from __future__ import annotations

import json

from langchain_core.messages import SystemMessage, HumanMessage

from aide.config import get_llm, load_prompt
from aide.state import AgentState


BLUEPRINT_INSTRUCTION = (
    "Based on the objective and any feedback, produce a Blueprint as a JSON array. "
    "Each element must have: task_id (int), description (str), tools_required (list[str]), "
    "success_criteria (str). Return ONLY the JSON array, no other text."
)


def architect(state: AgentState) -> dict:
    llm = get_llm("architect")
    system_prompt = load_prompt("architect")

    messages = [SystemMessage(content=system_prompt)]

    objective = state["objective"]
    feedback = state.get("review_feedback", "")
    escalation_log = state.get("execution_log", "")

    if feedback:
        user_content = (
            f"Objective: {objective}\n\n"
            f"Previous feedback / escalation:\n{feedback}\n\n"
            f"Execution log:\n{escalation_log}\n\n"
            f"{BLUEPRINT_INSTRUCTION}"
        )
    else:
        user_content = f"Objective: {objective}\n\n{BLUEPRINT_INSTRUCTION}"

    messages.append(HumanMessage(content=user_content))

    response = llm.invoke(messages)
    raw = response.content

    # Parse the blueprint JSON from the response
    try:
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        blueprint = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        blueprint = []

    return {
        "blueprint": blueprint,
        "current_task_idx": 0,
        "iteration_count": 0,
        "review_feedback": "",
        "execution_log": "",
        "messages": state.get("messages", []) + [response],
        "next_node": "human_review",
    }
