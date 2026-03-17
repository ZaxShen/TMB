"""UX helpers — auto-open files and detect saves for a friendlier workflow.

Cross-platform, stdlib-only. All functions are safe: never raise to caller.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("tmb.ux")


def open_in_editor(path: Path) -> bool:
    """Open a file in the user's default editor/viewer. Non-blocking.

    Returns True if the open command was launched, False on error.
    """
    try:
        import subprocess
        import sys as _sys

        path_str = str(path)
        if _sys.platform == "darwin":
            subprocess.Popen(["open", path_str])
        elif _sys.platform == "win32":
            import os
            os.startfile(path_str)
        else:
            # Linux and other Unix
            subprocess.Popen(["xdg-open", path_str])
        return True
    except Exception as exc:
        logger.debug("open_in_editor failed for %s: %s", path, exc)
        return False


def wait_for_file_change(path: Path, timeout: float = 300.0, poll_interval: float = 0.5) -> bool:
    """Wait until a file's mtime changes. Returns True if changed, False on timeout/error.

    Polls os.path.getmtime() at the given interval. Handles Ctrl+C gracefully.
    """
    try:
        import os
        import time

        if not path.exists():
            logger.debug("wait_for_file_change: file does not exist: %s", path)
            return False

        initial_mtime = os.path.getmtime(str(path))
        filename = path.name
        print(f"  Waiting for you to save {filename}... (Ctrl+C to skip)")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            time.sleep(poll_interval)
            try:
                current_mtime = os.path.getmtime(str(path))
            except OSError:
                return False
            if current_mtime != initial_mtime:
                return True

        return False

    except KeyboardInterrupt:
        print()  # clean line after ^C
        return False
    except Exception as exc:
        logger.debug("wait_for_file_change failed for %s: %s", path, exc)
        return False
