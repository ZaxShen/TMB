"""Tiny shared helpers — zero heavy imports."""

from __future__ import annotations

import os
import shutil


def _terminal_width() -> int:
    """Best-effort terminal width, default 100."""
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return 100


def truncate(text: str, maxlen: int = 75, suffix: str = "…") -> str:
    """Shorten *text* to *maxlen* chars on a word boundary.

    Cuts at the last space before *maxlen* so output never ends mid-word.
    Falls back to a hard cut if no space is found (single giant token).
    """
    if len(text) <= maxlen:
        return text
    cut = maxlen - len(suffix)
    # Try to break at a word boundary
    space = text.rfind(" ", 0, cut)
    if space > cut // 2:  # don't go too far back
        cut = space
    return text[:cut].rstrip() + suffix


def fit_line(*parts: str, sep: str = " ") -> str:
    """Join *parts* and truncate the last part to fit terminal width.

    Usage::

        fit_line(f"[EXECUTOR] 🔧 [{bid}] {total} tasks — starting:", description)

    The prefix (all parts except the last) is never truncated.
    The last part is trimmed to fill the remaining terminal width.
    """
    width = _terminal_width()
    if len(parts) <= 1:
        return truncate(sep.join(parts), width)
    prefix = sep.join(parts[:-1]) + sep
    remaining = max(20, width - len(prefix))
    return prefix + truncate(parts[-1], remaining)
