"""Discussion node — file-based Architect–Chief Architect Q&A before blueprint creation.

Flow:
  1. Architect writes questions to doc/DISCUSSION.md with an answer section
  2. Terminal prompts Chief Architect to edit the file, then press Enter
  3. System reads the answer from below a marker in the file
  4. Repeat until Architect says READY TO BUILD

The discussion is stored in SQLite (permanent) and doc/DISCUSSION.md (current).
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

from aide.config import get_llm, _AIDE_ROOT
from aide.permissions import assert_aide_write
from aide.store import Store


_DISCUSSION_SYSTEM = """You are a Senior Systems Architect. The Chief Architect has written goals in doc/GOALS.md.
Your job is to discuss these goals with the Chief Architect to clarify requirements before building a blueprint.

Rules:
- Ask focused, specific questions to eliminate ambiguity.
- Challenge assumptions if you see risks or contradictions.
- When you fully understand the requirements, say exactly: READY TO BUILD
- Keep each response concise — max 3-4 questions at a time.
- Number your questions so the Chief Architect can answer by number.
- Reference the project context when relevant.
"""

_READY_SIGNAL = "READY TO BUILD"
_ANSWER_MARKER = "---ANSWER-BELOW---"


def _write_discussion_file(
    path, store: Store, issue_id: int, *, waiting_for_answer: bool
):
    """Write doc/DISCUSSION.md with conversation history and optional answer section."""
    issue = store.get_issue(issue_id)
    discussions = store.get_discussions(issue_id)

    lines = [
        f"# Discussion — Issue #{issue_id}",
        "",
        f"**Objective**: {issue['objective']}",
        "",
    ]

    if waiting_for_answer:
        lines += [
            "> **Action required**: Answer the Architect's questions at the bottom of this file.",
            "> Save the file, then press **Enter** in the terminal to continue.",
            "",
        ]

    lines += ["---", ""]

    for d in discussions:
        label = "**Chief Architect**" if d["role"] == "cto" else "**Architect**"
        lines += [f"### {label}", ""]
        lines.append(d["content"])
        lines += ["", "---", ""]

    if waiting_for_answer:
        lines += [
            "## Your Answer",
            "",
            f"> Write your answers below the `{_ANSWER_MARKER}` line.",
            "> Do not edit anything above it. Save the file when done.",
            "",
            _ANSWER_MARKER,
            "",
            "",
        ]

    assert_aide_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def _read_cto_answer(path) -> str:
    """Read the Chief Architect's answer from below the marker in DISCUSSION.md."""
    if not path.exists():
        return ""
    content = path.read_text()
    if _ANSWER_MARKER not in content:
        return ""
    answer = content.split(_ANSWER_MARKER, 1)[1].strip()
    return answer


def run_discussion(goals_md: str, project_context: str, store: Store, issue_id: int) -> str:
    """File-based discussion loop. Returns the full discussion as a string."""
    llm = get_llm("architect")
    discussion_path = _AIDE_ROOT / "doc" / "DISCUSSION.md"

    initial_prompt = (
        f"## Project Context\n{project_context}\n\n"
        f"## Chief Architect's Goals\n{goals_md}\n\n"
        "Review these goals. Ask the Chief Architect any clarifying questions, "
        "or if everything is clear, say READY TO BUILD."
    )

    messages = [
        SystemMessage(content=_DISCUSSION_SYSTEM),
        HumanMessage(content=initial_prompt),
    ]

    prior = store.get_discussions(issue_id)
    needs_cto_input = False

    if prior:
        for d in prior:
            if d["role"] == "architect":
                messages.append(AIMessage(content=d["content"]))
            else:
                messages.append(HumanMessage(content=d["content"]))

        if prior[-1]["role"] == "architect":
            needs_cto_input = True
            _write_discussion_file(
                discussion_path, store, issue_id, waiting_for_answer=True
            )
            print()
            print(f"[DISCUSSION] Resuming — {len(prior)} messages from previous session.")
            print(f"[DISCUSSION] Architect's questions are in {discussion_path}")
        else:
            print()
            print(f"[DISCUSSION] Resuming — {len(prior)} messages from previous session.")
    else:
        print()
        print("[DISCUSSION] Architect is reviewing your goals...")

    while True:
        if not needs_cto_input:
            response = llm.invoke(messages)
            architect_msg = response.content

            store.add_discussion(issue_id, "architect", architect_msg)
            messages.append(AIMessage(content=architect_msg))

            print(f"\n[Architect]:\n{architect_msg}")

            if _READY_SIGNAL in architect_msg.upper():
                rounds = len(store.get_discussions(issue_id))
                store.log(issue_id, None, "architect", "discussion_complete", {
                    "rounds": rounds,
                }, summary=f"Discussion complete after {rounds} messages")
                _write_discussion_file(
                    discussion_path, store, issue_id, waiting_for_answer=False
                )
                print()
                print("-" * 40)
                print("[DISCUSSION] Requirements aligned. Proceeding to blueprint.")
                print(f"[AIDE] Discussion saved to doc/DISCUSSION.md")
                break
        else:
            needs_cto_input = False

        _write_discussion_file(
            discussion_path, store, issue_id, waiting_for_answer=True
        )

        print()
        print("[DISCUSSION] Edit your answers in doc/DISCUSSION.md")
        input("[DISCUSSION] Press Enter when done...")

        cto_answer = _read_cto_answer(discussion_path)
        if not cto_answer:
            cto_answer = "Proceed with your best judgment."

        store.add_discussion(issue_id, "cto", cto_answer)
        messages.append(HumanMessage(content=cto_answer))
        print(f"[Chief Architect]: {cto_answer[:120]}...")

    discussion_md = store.export_discussion_md(issue_id)
    return discussion_md
