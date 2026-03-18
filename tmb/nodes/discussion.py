"""Discussion node — file-based Planner–Owner Q&A before blueprint creation.

Flow:
  1. Planner writes questions to bro/DISCUSSION.md with an answer section
  2. Terminal prompts the Project Owner to edit the file, then press Enter
  3. System reads the answer from below a marker in the file
  4. Repeat until Planner says TRUST ME BRO, LET'S BUILD

The discussion is stored in SQLite (permanent) and bro/DISCUSSION.md (current).
"""

from __future__ import annotations

import re

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from tmb.config import get_llm, get_role_name, get_project_root, load_nodes_config, extract_token_usage, safe_llm_invoke, LLMConnectionError
from tmb.paths import docs_dir
from tmb.utils import truncate
from tmb.store import Store
from tmb.tools import get_tools_for_node
from tmb.types import TokenAccumulator


_DISCUSSION_SYSTEM = """You are a {role_planner} — but honestly, just call you Bro. \
You're a reliable bot who handles the {role_owner}'s goals and makes them work.

The {role_owner} has written goals in bro/GOALS.md. Your job is to discuss these goals \
with the {role_owner} to fully align on requirements before building a blueprint.

You have access to `file_inspect` and `search` tools. BEFORE asking the {role_owner} any question, \
check if you can answer it yourself by inspecting files or searching the codebase. \
For example, if the goals mention a CSV file, use `file_inspect` to learn the column schema \
instead of asking the {role_owner} to list the columns.

Personality — you're a chill but sharp bro:
- Talk casually but think rigorously. You're relaxed in tone, precise in substance.
- Start the conversation by greeting the {role_owner} warmly and summarizing what you see in their goals.
- Use phrases like "Bro, I got it", "Let me deep dive into this", "Now I have the full picture", \
  "Let's make sure I fully align with your requirements".
- When you spot risks or issues, say it straight: "Heads up bro, I see a potential issue here..."
- Stay focused — don't ramble. Max 3-4 questions at a time, numbered so the {role_owner} can answer by number.
- Explore first, ask second. Only ask the {role_owner} things you genuinely cannot determine from the codebase.
- Challenge assumptions if you see risks or contradictions.
- When you fully understand the requirements and are confident you can build it, say exactly: \
  TRUST ME BRO, LET'S BUILD
- Reference the project context when relevant.
"""

_READY_SIGNAL = "TRUST ME BRO, LET'S BUILD"
_ANSWER_MARKER = "---ANSWER-BELOW---"


def _write_discussion_file(
    path, store: Store, issue_id: int, *, waiting_for_answer: bool
):
    """Write bro/DISCUSSION.md with conversation history and optional answer section."""
    issue = store.get_issue(issue_id)
    discussions = store.get_discussions(issue_id)
    planner_display = get_role_name("planner")
    owner_display = get_role_name("owner")

    lines = [
        f"# Discussion — Issue #{issue_id}",
        "",
        f"**Objective**: {issue['objective']}",
        "",
    ]

    if waiting_for_answer:
        lines += [
            f"> **Action required**: Answer the {planner_display}'s questions at the bottom of this file.",
            "> Save the file, then press **Enter** in the terminal to continue.",
            "",
        ]

    lines += ["---", ""]

    for d in discussions:
        label = f"**{owner_display}**" if d["role"] in ("owner", "cto") else f"**{planner_display}**"
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

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def _read_owner_answer(path) -> str:
    """Read the owner's answer from below the marker in DISCUSSION.md."""
    if not path.exists():
        return ""
    content = path.read_text()
    if _ANSWER_MARKER not in content:
        return ""
    answer = content.split(_ANSWER_MARKER, 1)[1].strip()
    return answer


def _has_questions(message: str) -> bool:
    """Detect if a planner message contains questions for the owner."""
    # Numbered questions: "1." or "1)" at start of line
    if re.search(r'^\s*\d+[.)]\s', message, re.MULTILINE):
        return True
    # Question marks (at least one)
    if '?' in message:
        return True
    return False


_MAX_AUTO_PROCEED = 3
_MAX_TOOL_ROUNDS = 10


def _run_discussion_tool_loop(llm_with_tools, messages, tool_map,
                              token_accum: "TokenAccumulator | None" = None,
                              audit_store=None, audit_issue_id=None):
    """Let the planner use tools (file_inspect, search) before responding to the owner."""
    import sys
    import time
    start = time.monotonic()
    counts: dict[str, int] = {}
    response = None
    prefix = "  [discuss] "

    def _print_progress(final: bool = False):
        elapsed = time.monotonic() - start
        parts = [f"{v} {k}" for k, v in sorted(counts.items())]
        line = f"{prefix}{', '.join(parts)} ({elapsed:.0f}s)"
        if final:
            print(f"\r{line}{'':20}")
        else:
            sys.stdout.write(f"\r{line}...{'':20}")
            sys.stdout.flush()

    for _rnd in range(_MAX_TOOL_ROUNDS):
        if counts:
            _print_progress()
        response = safe_llm_invoke(llm_with_tools, messages, label="discussion")
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
                # Audit logging
                if audit_store is not None and audit_issue_id is not None:
                    is_truncated = len(result_str) > 8000
                    audit_store.log_audit(
                        audit_issue_id, None, _rnd, tc["name"],
                        tc.get("args", {}), result_str, is_truncated=is_truncated,
                        from_node="discussion",
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


def run_discussion(goals_md: str, project_context: str, store: Store, issue_id: int) -> str:
    """File-based discussion loop. Returns the full discussion as a string."""
    try:
        return _run_discussion_impl(goals_md, project_context, store, issue_id)
    except LLMConnectionError as e:
        planner_display = get_role_name("planner").upper()
        print(f"\n[{planner_display}] ❌ LLM connection error:\n{e}\n")
        store.log(issue_id, None, "planner", "llm_connection_error", {
            "error": str(e)[:500],
        }, summary=f"LLM connection error: {str(e)[:100]}")
        return ""


def _run_discussion_impl(goals_md: str, project_context: str, store: Store, issue_id: int) -> str:
    """Inner implementation — may raise LLMConnectionError."""
    llm = get_llm("planner")
    discussion_path = docs_dir() / "DISCUSSION.md"
    planner_display = get_role_name("planner")
    owner_display = get_role_name("owner")

    node_cfg = load_nodes_config().get("planner", {})
    project_root = str(get_project_root())
    read_only_tools = ["file_inspect", "file_read", "search"]
    tool_names = [t for t in node_cfg.get("tools", []) if t in read_only_tools]
    tools = get_tools_for_node(tool_names, project_root, node_name="planner")
    tool_map = {t.name: t for t in tools} if tools else {}
    llm_with_tools = llm.bind_tools(tools) if tools else llm

    system_text = _DISCUSSION_SYSTEM
    for var, display in {
        "{role_planner}": planner_display,
        "{role_owner}": owner_display,
    }.items():
        system_text = system_text.replace(var, display)

    initial_prompt = (
        f"## Project Context\n{project_context}\n\n"
        f"## {owner_display}'s Goals\n{goals_md}\n\n"
        f"Hey bro! Start by greeting the {owner_display} — introduce yourself as their "
        f"reliable Bro who's here to handle their goals and make them work. "
        f"Then use your tools to explore relevant files first "
        f"(e.g., read CSVs, scripts, configs) before asking questions. "
        f"Only ask the {owner_display} things you genuinely cannot determine yourself. "
        "If everything is clear, say TRUST ME BRO, LET'S BUILD."
    )

    messages = [
        SystemMessage(content=system_text),
        HumanMessage(content=initial_prompt),
    ]

    prior = store.get_discussions(issue_id)
    needs_owner_input = False

    if prior:
        for d in prior:
            if d["role"] in ("planner", "architect"):
                messages.append(AIMessage(content=d["content"]))
            else:
                messages.append(HumanMessage(content=d["content"]))

        if prior[-1]["role"] in ("planner", "architect"):
            needs_owner_input = True
            _write_discussion_file(
                discussion_path, store, issue_id, waiting_for_answer=True
            )
            print()
            print(f"[DISCUSSION] Resuming — {len(prior)} messages from previous session.")
            print(f"[DISCUSSION] {planner_display}'s questions are in {discussion_path}")
        else:
            print()
            print(f"[DISCUSSION] Resuming — {len(prior)} messages from previous session.")
    else:
        print()
        print(f"[DISCUSSION] Yo, your Bro is checking out your goals... 🤙")

    token_accum = TokenAccumulator()
    auto_proceed_count = 0
    while True:
        if not needs_owner_input:
            response, messages = _run_discussion_tool_loop(
                llm_with_tools, messages, tool_map, token_accum=token_accum,
                audit_store=store, audit_issue_id=issue_id,
            )
            planner_msg = response.content
            if isinstance(planner_msg, list):
                planner_msg = "\n".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in planner_msg
                )

            store.add_discussion(issue_id, "planner", planner_msg)

            print(f"\n[{planner_display}]:\n{planner_msg}")

            if _READY_SIGNAL in planner_msg.upper():
                rounds = len(store.get_discussions(issue_id))
                store.log(issue_id, None, "planner", "discussion_complete", {
                    "rounds": rounds,
                }, summary=f"Discussion complete after {rounds} messages")
                _write_discussion_file(
                    discussion_path, store, issue_id, waiting_for_answer=False
                )
                print()
                print("  ─────────────────────────────────")
                print("  🤙 Trust me bro, we're aligned. Let's build this thing.")
                dd = docs_dir().name
                print(f"  Discussion saved → {dd}/DISCUSSION.md")
                break

            # Check if the planner asked questions
            if not _has_questions(planner_msg):
                # No questions — auto-proceed instead of blocking
                auto_proceed_count += 1
                if auto_proceed_count >= _MAX_AUTO_PROCEED:
                    # Safety: force the planner to commit after too many rounds with no questions
                    print()
                    print(f"  [DISCUSSION] Auto-proceeded {_MAX_AUTO_PROCEED} times — forcing alignment.")
                    auto_response = "Please finalize your analysis and say TRUST ME BRO, LET'S BUILD."
                else:
                    print(f"  [DISCUSSION] No questions — proceeding automatically.")
                    auto_response = "No questions to answer. Proceed with your best judgment."

                store.add_discussion(issue_id, "owner", auto_response)
                messages.append(HumanMessage(content=auto_response))
                continue  # Skip user prompt, go back to LLM

            auto_proceed_count = 0  # Reset on user interaction
        else:
            needs_owner_input = False

        _write_discussion_file(
            discussion_path, store, issue_id, waiting_for_answer=True
        )

        print()
        from tmb.ux import open_in_editor, wait_for_file_change
        open_in_editor(discussion_path)
        print(f"  Answer in {docs_dir().name}/DISCUSSION.md — save when done. (Ctrl+C to skip)")
        if not wait_for_file_change(discussion_path):
            print("  No changes detected — proceeding with defaults.")

        owner_answer = _read_owner_answer(discussion_path)
        if not owner_answer:
            owner_answer = "Proceed with your best judgment."

        store.add_discussion(issue_id, "owner", owner_answer)
        messages.append(HumanMessage(content=owner_answer))
        print(f"[{owner_display}]: {truncate(owner_answer, 120)}")

    store.log_tokens(issue_id, "planner", token_accum.input_tokens, token_accum.output_tokens)
    discussion_md = store.export_discussion_md(issue_id)
    return discussion_md
