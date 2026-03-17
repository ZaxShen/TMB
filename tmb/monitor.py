"""Terminal dashboard renderer for TMB execution state.

Reads live data from the SQLite store and renders an ANSI box-drawn dashboard
as a string. All functions that accept a ``store`` parameter expect an already-
connected ``Store`` instance. ``run_monitor_loop`` creates its own connection
because it runs in a background thread.
"""

from __future__ import annotations

import shutil
import sys
import threading
from datetime import datetime, timezone

from tmb.store import Store


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_terminal() -> bool:
    """Return True when stdout is connected to a real terminal (not piped)."""
    return sys.stdout.isatty()


def _format_elapsed(start_iso: str | None) -> str:
    """Convert an ISO-8601 UTC timestamp to a human-readable elapsed string.

    Returns:
        ``"Xs"`` for less than 60 seconds.
        ``"Xm Ys"`` for less than one hour.
        ``"Xh Ym"`` for one hour or more.
        ``"—"`` for ``None`` or unparseable input.
    """
    if not start_iso:
        return "\u2014"
    try:
        # Handle both offset-aware and naive timestamps produced by store
        start = datetime.fromisoformat(start_iso)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        elapsed = int((datetime.now(timezone.utc) - start).total_seconds())
        if elapsed < 0:
            elapsed = 0
        if elapsed < 60:
            return f"{elapsed}s"
        if elapsed < 3600:
            minutes = elapsed // 60
            seconds = elapsed % 60
            return f"{minutes}m {seconds}s"
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        return f"{hours}h {minutes}m"
    except (ValueError, TypeError, OverflowError):
        return "\u2014"


def _task_icon(status: str) -> str:
    """Return a single emoji icon for a task status string."""
    icons = {
        "completed": "\u2705",    # ✅
        "in_progress": "\U0001f527",  # 🔧
        "pending": "\u23f3",      # ⏳
        "failed": "\u274c",       # ❌
        "escalated": "\u26a0\ufe0f",  # ⚠️
    }
    return icons.get(status, "\u2753")  # ❓


def _format_tokens(n: int) -> str:
    """Format a token count into a compact human-readable string."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    return f"{n / 1_000_000:.1f}M"


# ---------------------------------------------------------------------------
# Dashboard renderer
# ---------------------------------------------------------------------------

def render_dashboard(store: Store, issue_id: int, width: int = 80) -> str:
    """Render a full ANSI box-drawn dashboard and return it as a string.

    Never prints. Adapts all columns to ``width``. If the issue is not found
    returns a minimal "Issue not found" message.
    """
    issue = store.get_issue(issue_id)
    if issue is None:
        return f"Issue #{issue_id} not found."

    tasks = store.get_tasks_overview(issue_id)
    token_summary = store.get_token_summary(issue_id)
    audit_log = store.get_audit_log(issue_id)

    # --- dimensions ---------------------------------------------------------
    # A content line is: ║ + SP + SP + content + padding + SP + SP + ║
    # That is 1 + 2 + content_width + 2 + 1 = content_width + 6
    # So inner (the space available for content) = width - 6
    inner = width - 6

    # --- helper: pad a content line to fill the box -------------------------
    def box_line(content: str) -> str:
        """Wrap content in box borders, padding with spaces to ``width``."""
        # Visible length accounting for multi-byte/emoji characters isn't
        # trivial. We use a simple approach: measure len() of the string with
        # ANSI escape sequences stripped, which is good enough for plain emoji.
        visible = _visible_len(content)
        padding = inner - visible
        if padding < 0:
            # Truncate — strip trailing chars until it fits, add ellipsis
            content = _truncate_visible(content, inner - 1) + "\u2026"
            padding = 0
        return f"\u2551  {content}{' ' * padding}  \u2551"

    def separator() -> str:
        return "\u2560" + "\u2550" * (width - 2) + "\u2563"

    # --- header -------------------------------------------------------------
    # top_border: ╔ + ═*left_pad + SP + title + SP + ═*right_pad + ╗
    # visible width = 1 + left_pad + 1 + len(title) + 1 + right_pad + 1 = width
    # => right_pad = width - 4 - left_pad - len(title)
    header_title = "TMB"
    left_pad = 2
    right_pad = width - 4 - left_pad - len(header_title)
    if right_pad < 0:
        right_pad = 0
    top_border = (
        "\u2554"
        + "\u2550" * left_pad
        + " "
        + header_title
        + " "
        + "\u2550" * right_pad
        + "\u2557"
    )

    bottom_border = "\u255a" + "\u2550" * (width - 2) + "\u255d"

    lines: list[str] = [top_border]

    # --- issue line ---------------------------------------------------------
    objective = issue.get("objective") or ""
    issue_label = f"Issue #{issue_id}: {objective}"
    lines.append(box_line(issue_label))

    # --- status / elapsed line ----------------------------------------------
    status = issue.get("status") or "unknown"
    elapsed = _format_elapsed(issue.get("created_at"))
    status_elapsed = f"Status: {status}  \u2502  Elapsed: {elapsed}"
    lines.append(box_line(status_elapsed))

    lines.append(separator())

    # --- tasks section ------------------------------------------------------
    completed_count = sum(1 for t in tasks if t.get("status") == "completed")
    total_count = len(tasks)
    tasks_header = f"Tasks [{completed_count}/{total_count}]"
    lines.append(box_line(tasks_header))

    for task in tasks:
        icon = _task_icon(task.get("status", ""))
        task_id = task.get("id", "?")
        title = task.get("title") or "(no title)"
        task_status = task.get("status", "")

        # right-side annotation
        if task_status == "completed":
            elapsed_str = _format_elapsed(task.get("completed_at") or task.get("updated_at"))
            # We don't have per-task token counts in overview, so omit tokens
            annotation = f"{elapsed_str}"
        elif task_status == "in_progress":
            annotation = "running"
        else:
            annotation = "pending"

        # "[N] Title" left part + annotation right-aligned
        left_part = f"{icon} [{task_id}] {title}"
        # Total inner = inner chars
        # We want: "  left_part ... annotation  " to fill inner
        annotation_width = len(annotation)
        # 2 spaces between left and annotation minimum
        max_left = inner - annotation_width - 2
        left_visible = _visible_len(left_part)
        if left_visible > max_left:
            left_part = _truncate_visible(left_part, max_left - 1) + "\u2026"
            left_visible = max_left
        gap = inner - left_visible - annotation_width
        task_line = left_part + " " * gap + annotation
        lines.append(box_line(task_line))

    lines.append(separator())

    # --- token / tool summary line ------------------------------------------
    total_tok = token_summary.get("total", {})
    tok_in = total_tok.get("in", 0)
    tok_out = total_tok.get("out", 0)
    tool_calls = len(audit_log)

    tok_str = f"Tokens: {_format_tokens(tok_in)} in / {_format_tokens(tok_out)} out"
    tools_str = f"Tools: {tool_calls} calls"
    summary_line = f"{tok_str}  \u2502  {tools_str}"
    lines.append(box_line(summary_line))

    lines.append(bottom_border)
    lines.append("  Refreshing every 2s... (Ctrl+C to exit)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Clear + render
# ---------------------------------------------------------------------------

def clear_and_render(store: Store, issue_id: int) -> None:
    """Clear the terminal and print a fresh dashboard to stdout."""
    cols = shutil.get_terminal_size().columns
    dashboard = render_dashboard(store, issue_id, width=cols)
    sys.stdout.write("\033[2J\033[H" + dashboard + "\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# Background monitor loop
# ---------------------------------------------------------------------------

def run_monitor_loop(
    store_path: str,
    issue_id: int,
    stop_event: threading.Event,
    output_fd,
) -> None:
    """Poll the store every 2 seconds and render the dashboard to ``output_fd``.

    Creates its own ``Store`` connection — never accepts a Store object —
    because SQLite connections must not be shared across threads.

    Catches all exceptions inside the loop so it never crashes the main
    execution thread. Renders one final dashboard after ``stop_event`` is set.
    """
    try:
        store = Store(db_path=store_path)
    except Exception:
        return

    def _render_to_fd() -> None:
        try:
            cols = shutil.get_terminal_size().columns
            dashboard = render_dashboard(store, issue_id, width=cols)
            output_fd.write("\033[2J\033[H" + dashboard + "\n")
            output_fd.flush()
        except Exception:
            pass  # Never crash the monitor loop

    while not stop_event.is_set():
        _render_to_fd()
        # Sleep in small increments so we react to stop_event promptly
        stop_event.wait(timeout=2.0)

    # Final render after stop
    _render_to_fd()


# ---------------------------------------------------------------------------
# Internal string-width helpers
# ---------------------------------------------------------------------------

def _visible_len(s: str) -> int:
    """Approximate visible character width.

    Counts each code point as 1, except for emoji and wide CJK characters
    which we count as 2, and variation selectors / zero-width joiners as 0.
    This is intentionally simple — it handles the ASCII + emoji mix used in
    the dashboard without pulling in third-party libraries.
    """
    width = 0
    for ch in s:
        cp = ord(ch)
        # Variation selectors, zero-width joiners, combining marks
        if cp in (0xFE0F, 0x200D) or (0x300 <= cp <= 0x36F):
            continue
        # Emoji range (broad) and CJK ideographs
        if (
            (0x1F000 <= cp <= 0x1FFFF)
            or (0x2600 <= cp <= 0x27BF)
            or (0x2300 <= cp <= 0x23FF)
            or (0x2700 <= cp <= 0x27FF)
            or (0x4E00 <= cp <= 0x9FFF)
            or (0x3400 <= cp <= 0x4DBF)
            or (0xF900 <= cp <= 0xFAFF)
        ):
            width += 2
        else:
            width += 1
    return width


def _truncate_visible(s: str, max_width: int) -> str:
    """Truncate ``s`` so its visible width does not exceed ``max_width``."""
    width = 0
    result = []
    for ch in s:
        cp = ord(ch)
        # Zero-width chars: append without counting
        if cp in (0xFE0F, 0x200D) or (0x300 <= cp <= 0x36F):
            result.append(ch)
            continue
        if (
            (0x1F000 <= cp <= 0x1FFFF)
            or (0x2600 <= cp <= 0x27BF)
            or (0x2300 <= cp <= 0x23FF)
            or (0x2700 <= cp <= 0x27FF)
            or (0x4E00 <= cp <= 0x9FFF)
            or (0x3400 <= cp <= 0x4DBF)
            or (0xF900 <= cp <= 0xFAFF)
        ):
            ch_width = 2
        else:
            ch_width = 1
        if width + ch_width > max_width:
            break
        result.append(ch)
        width += ch_width
    return "".join(result)
