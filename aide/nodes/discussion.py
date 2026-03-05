"""Discussion node — interactive Architect-CTO Q&A before blueprint creation.

This node is NOT part of the LangGraph — it runs before the graph starts,
because LangGraph nodes can't do interactive terminal I/O mid-graph.
The discussion is stored in SQLite and exported to doc/DISCUSSION.md.
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from aide.config import get_llm, load_prompt, get_project_root, _AIDE_ROOT
from aide.permissions import assert_aide_write
from aide.store import Store


_DISCUSSION_SYSTEM = """You are a Senior Systems Architect. The CTO has written goals in doc/GOALS.md.
Your job is to discuss these goals with the CTO to clarify requirements before building a blueprint.

Rules:
- Ask focused, specific questions to eliminate ambiguity.
- Challenge assumptions if you see risks or contradictions.
- When you fully understand the requirements, say exactly: READY TO BUILD
- Keep each response concise — max 3-4 questions at a time.
- Reference the project context when relevant.
"""

_READY_SIGNAL = "READY TO BUILD"


def run_discussion(goals_md: str, project_context: str, store: Store, issue_id: int) -> str:
    """Interactive discussion loop. Returns the full discussion as a string.

    If the DB already has discussion rows for this issue (resume scenario),
    reconstruct the LLM message history so the Architect has full context.
    """
    llm = get_llm("architect")
    doc_dir = _AIDE_ROOT / "doc"

    initial_prompt = (
        f"## Project Context\n{project_context}\n\n"
        f"## CTO's Goals\n{goals_md}\n\n"
        "Review these goals. Ask the CTO any clarifying questions, "
        "or if everything is clear, say READY TO BUILD."
    )

    messages = [
        SystemMessage(content=_DISCUSSION_SYSTEM),
        HumanMessage(content=initial_prompt),
    ]

    prior = store.get_discussions(issue_id)
    if prior:
        for d in prior:
            if d["role"] == "architect":
                messages.append(AIMessage(content=d["content"]))
            else:
                messages.append(HumanMessage(content=d["content"]))
        print()
        print(f"[DISCUSSION] Resuming from previous session ({len(prior)} messages)...")
        print("(Type your answers. The Architect will ask follow-ups until requirements are clear.)")
        print("-" * 40)
    else:
        print()
        print("[DISCUSSION] Architect is reviewing your goals...")
        print("(Type your answers. The Architect will ask follow-ups until requirements are clear.)")
        print("-" * 40)

    while True:
        response = llm.invoke(messages)
        architect_msg = response.content

        store.add_discussion(issue_id, "architect", architect_msg)
        messages.append(AIMessage(content=architect_msg))

        print(f"\n[Architect]:\n{architect_msg}")

        if _READY_SIGNAL in architect_msg.upper():
            store.log(issue_id, None, "architect", "discussion_complete", {
                "rounds": len(store.get_discussions(issue_id)),
            })
            print()
            print("-" * 40)
            print("[DISCUSSION] Requirements aligned. Proceeding to blueprint.")
            break

        print()
        cto_input = input("[CTO]: ").strip()
        if not cto_input:
            cto_input = "Proceed with your best judgment."

        store.add_discussion(issue_id, "cto", cto_input)
        messages.append(HumanMessage(content=cto_input))

    discussion_md = store.export_discussion_md(issue_id)
    doc_dir.mkdir(parents=True, exist_ok=True)
    discussion_path = doc_dir / "DISCUSSION.md"
    assert_aide_write(discussion_path)
    discussion_path.write_text(discussion_md)
    print(f"[AIDE] Discussion saved to doc/DISCUSSION.md")

    return discussion_md
