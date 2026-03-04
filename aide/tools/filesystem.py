"""File read/write tools — sandboxed to project root."""

from __future__ import annotations

from pathlib import Path

from langchain_core.tools import tool


def _resolve_safe(project_root: str, file_path: str) -> Path:
    """Resolve a path and ensure it stays within project root."""
    root = Path(project_root).resolve()
    target = (root / file_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(f"Path escapes project root: {file_path}")
    return target


def create_file_read_tool(project_root: str):
    @tool
    def file_read(file_path: str) -> str:
        """Read a file relative to the project root. Returns the file contents."""
        target = _resolve_safe(project_root, file_path)
        if not target.exists():
            return f"[error] File not found: {file_path}"
        return target.read_text()

    return file_read


def create_file_write_tool(project_root: str):
    @tool
    def file_write(file_path: str, content: str) -> str:
        """Write content to a file relative to the project root. Creates parent directories if needed."""
        target = _resolve_safe(project_root, file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"Wrote {len(content)} bytes to {file_path}"

    return file_write
