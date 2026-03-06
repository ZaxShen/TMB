"""Discussion node — file-based Planner–Owner Q&A before blueprint creation.

Flow:
  1. Planner writes questions to doc/DISCUSSION.md with an answer section
  2. Terminal prompts the Project Owner to edit the file, then press Enter
  3. System reads the answer from below a marker in the file
  4. Repeat until Planner says READY TO BUILD

The discussion is stored in SQLite (permanent) and doc/DISCUSSION.md (current).
"""

from __future__ import annotations

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage

from baymax.config import get_llm, get_role_name, get_project_root, load_nodes_config, _BAYMAX_ROOT, extract_token_usage
from baymax.permissions import assert_baymax_write
from baymax.store import Store
from baymax.tools import get_tools_for_node


_DISCUSSION_SYSTEM = """You are a {role_planner}. The {role_owner} has written goals in doc/GOALS.md.
Your job is to discuss these goals with the {role_owner} to clarify requirements before building a blueprint.

You have access to `file_inspect` and `search` tools. BEFORE asking the {role_owner} any question,
check if you can answer it yourself by inspecting files or searching the codebase.
For example, if the goals mention a CSV file, use `file_inspect` to learn the column schema
instead of asking the {role_owner} to list the columns.

Rules:
- Explore first, ask second. Only ask the {role_owner} things you genuinely cannot determine from the codebase.
- Ask focused, specific questions to eliminate ambiguity.
- Challenge assumptions if you see risks or contradictions.
- When you fully understand the requirements, say exactly: READY TO BUILD
- Keep each response concise — max 3-4 questions at a time.
- Number your questions so the {role_owner} can answer by number.
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

    assert_baymax_write(path)
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


_MAX_TOOL_ROUNDS = 10


def _run_discussion_tool_loop(llm_with_tools, messages, tool_map, token_accum: dict | None = None):
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

    for _ in range(_MAX_TOOL_ROUNDS):
        if counts:
            _print_progress()
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if token_accum is not None:
            usage = extract_token_usage(response)
            token_accum["input_tokens"] = token_accum.get("input_tokens", 0) + usage["input_tokens"]
            token_accum["output_tokens"] = token_accum.get("output_tokens", 0) + usage["output_tokens"]

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
    llm = get_llm("planner")
    discussion_path = _BAYMAX_ROOT / "doc" / "DISCUSSION.md"
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
        f"Review these goals. Use your tools to explore relevant files first "
        f"(e.g., read CSVs, scripts, configs), then ask the {owner_display} "
        "only questions you cannot answer yourself. "
        "If everything is clear, say READY TO BUILD."
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
        print(f"[DISCUSSION] {planner_display} is reviewing your goals...")

    token_accum = {"input_tokens": 0, "output_tokens": 0}
    while True:
        if not needs_owner_input:
            response, messages = _run_discussion_tool_loop(llm_with_tools, messages, tool_map, token_accum=token_accum)
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
                print("-" * 40)
                print("[DISCUSSION] Requirements aligned. Proceeding to blueprint.")
                print(f"[Baymax] Discussion saved to doc/DISCUSSION.md")
                break
        else:
            needs_owner_input = False

        _write_discussion_file(
            discussion_path, store, issue_id, waiting_for_answer=True
        )

        print()
        print("[DISCUSSION] Edit your answers in doc/DISCUSSION.md")
        input("[DISCUSSION] Press Enter when done...")

        owner_answer = _read_owner_answer(discussion_path)
        if not owner_answer:
            owner_answer = "Proceed with your best judgment."

        store.add_discussion(issue_id, "owner", owner_answer)
        messages.append(HumanMessage(content=owner_answer))
        print(f"[{owner_display}]: {owner_answer[:120]}...")

    store.log_tokens(issue_id, "planner", token_accum["input_tokens"], token_accum["output_tokens"])
    discussion_md = store.export_discussion_md(issue_id)
    return discussion_md
