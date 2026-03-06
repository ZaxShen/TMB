"""File read/write/inspect tools — sandboxed to project root, blacklist + node access enforced.

All inspectors use **stdlib only**. Agents that need richer analysis (pandas, openpyxl,
pymupdf, etc.) should use the shell tool and create a Skill for reuse.
"""

from __future__ import annotations

import csv as _csv
import json as _json
import struct
from pathlib import Path

from langchain_core.tools import tool

from baymax.permissions import assert_not_blacklisted, assert_node_access


def _resolve_safe(project_root: str, file_path: str) -> Path:
    """Resolve a path and ensure it stays within project root."""
    root = Path(project_root).resolve()
    target = (root / file_path).resolve()
    if not str(target).startswith(str(root)):
        raise ValueError(f"Path escapes project root: {file_path}")
    return target


# ── Lightweight stdlib-only inspectors ────────────────────────

def _inspect_csv(path: Path, head: int) -> str:
    """Parse header + first N rows using stdlib csv. No pandas."""
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        sample_bytes = f.read(8192)
        f.seek(0)
        dialect = _csv.Sniffer().sniff(sample_bytes) if sample_bytes else _csv.excel
        reader = _csv.reader(f, dialect)
        header = next(reader, None)
        if header is None:
            return f"CSV: {path.name} — empty file"
        rows: list[list[str]] = []
        for i, row in enumerate(reader):
            if i >= head:
                break
            rows.append(row)
        remaining = sum(1 for _ in reader)
    total = len(rows) + remaining
    col_widths = [max(len(h), *(len(r[j]) if j < len(r) else 0 for r in rows)) for j, h in enumerate(header)]
    def _fmt(vals: list[str]) -> str:
        return " | ".join(v.ljust(min(w, 40))[:40] for v, w in zip(vals, col_widths))
    table = [_fmt(header), "-+-".join("-" * min(w, 40) for w in col_widths)]
    for r in rows:
        padded = r + [""] * (len(header) - len(r))
        table.append(_fmt(padded))
    return "\n".join([
        f"CSV: {path.name}",
        f"Rows: ~{total}  Columns: {len(header)}",
        f"Column names: {header}",
        f"\nFirst {len(rows)} rows:",
        *table,
    ])


def _inspect_json(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        data = _json.loads(raw)
    except _json.JSONDecodeError as e:
        return f"JSON: {path.name} (parse error: {e})\nFirst 500 chars:\n{raw[:500]}"

    if isinstance(data, list):
        summary = f"JSON array with {len(data)} items"
        if data:
            first = data[0]
            if isinstance(first, dict):
                summary += f"\nItem keys: {list(first.keys())}"
            sample = _json.dumps(data[:3], indent=2, default=str)
            if len(sample) > 2000:
                sample = sample[:2000] + "\n... (truncated)"
            summary += f"\nFirst 3 items:\n{sample}"
    elif isinstance(data, dict):
        summary = f"JSON object with {len(data)} top-level keys"
        summary += f"\nKeys: {list(data.keys())}"
        sample = _json.dumps(data, indent=2, default=str)
        if len(sample) > 2000:
            sample = sample[:2000] + "\n... (truncated)"
        summary += f"\nContent:\n{sample}"
    else:
        summary = f"JSON scalar: {type(data).__name__} = {str(data)[:500]}"

    return f"JSON: {path.name}\n{summary}"


def _inspect_image(path: Path) -> str:
    size_bytes = path.stat().st_size
    ext = path.suffix.lower()
    dims = "unknown"
    try:
        with open(path, "rb") as f:
            header = f.read(32)
            if ext == ".png" and header[:8] == b"\x89PNG\r\n\x1a\n":
                w, h = struct.unpack(">II", header[16:24])
                dims = f"{w} x {h}"
            elif ext in (".jpg", ".jpeg"):
                f.seek(0)
                data = f.read()
                idx = 2
                while idx < len(data) - 1:
                    marker = data[idx:idx + 2]
                    if marker[0] != 0xFF:
                        break
                    if marker[1] in (0xC0, 0xC2):
                        h, w = struct.unpack(">HH", data[idx + 5:idx + 9])
                        dims = f"{w} x {h}"
                        break
                    length = struct.unpack(">H", data[idx + 2:idx + 4])[0]
                    idx += 2 + length
            elif ext == ".gif" and header[:6] in (b"GIF87a", b"GIF89a"):
                w, h = struct.unpack("<HH", header[6:10])
                dims = f"{w} x {h}"
    except Exception:
        pass

    size_str = (
        f"{size_bytes / 1_048_576:.1f} MB" if size_bytes > 1_048_576
        else f"{size_bytes / 1024:.1f} KB"
    )
    return f"Image: {path.name}\nFormat: {ext.lstrip('.')}\nDimensions: {dims}\nSize: {size_str}"


def _inspect_binary(path: Path) -> str:
    """Fallback for any non-text format the tool doesn't natively handle."""
    size_bytes = path.stat().st_size
    with open(path, "rb") as f:
        hex_preview = f.read(32).hex(" ")
    size_str = (
        f"{size_bytes / 1_048_576:.1f} MB" if size_bytes > 1_048_576
        else f"{size_bytes / 1024:.1f} KB"
    )
    return (
        f"Binary: {path.name}\n"
        f"Extension: {path.suffix}\n"
        f"Size: {size_str}\n"
        f"First 32 bytes (hex): {hex_preview}\n"
        "[Use shell to probe further, then create a Skill for this format.]"
    )


def _inspect_text(path: Path, max_lines: int = 80) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return _inspect_binary(path)

    lines = text.splitlines()
    total = len(lines)
    if total > max_lines:
        preview = "\n".join(lines[:max_lines])
        return f"Text: {path.name} ({total} lines, showing first {max_lines})\n\n{preview}\n... ({total - max_lines} more lines)"
    return f"Text: {path.name} ({total} lines)\n\n{text}"


# ── Tool factories ────────────────────────────────────────────

_TEXT_EXTENSIONS = {
    ".csv", ".tsv", ".json", ".jsonl",
    ".md", ".txt", ".py", ".js", ".ts", ".yaml", ".yml", ".toml",
    ".html", ".css", ".xml", ".sql", ".sh", ".bash", ".zsh",
    ".rs", ".go", ".java", ".c", ".cpp", ".h", ".hpp", ".rb",
    ".r", ".jl", ".lua", ".swift", ".kt",
}
_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".svg"}


def create_file_inspect_tool(project_root: str, node_name: str = "planner"):
    @tool
    def file_inspect(file_path: str, head: int = 5) -> str:
        """Inspect a file and return a structured summary. Uses only Python stdlib —
        no external libraries. For richer analysis, use the shell tool and create a Skill.

        Handles: CSV/TSV (header + sample rows), JSON (structure + keys), images (dimensions),
        text/code (first lines). Unknown binary formats return metadata + hex preview.

        Args:
            file_path: Path relative to the project root.
            head: Number of sample rows for tabular files (default 5).
        """
        assert_not_blacklisted(file_path)
        assert_node_access(file_path, node_name)
        target = _resolve_safe(project_root, file_path)
        if not target.exists():
            return f"[error] File not found: {file_path}"

        ext = target.suffix.lower()

        try:
            if ext in (".csv", ".tsv"):
                return _inspect_csv(target, head)
            if ext in (".json", ".jsonl"):
                return _inspect_json(target)
            if ext in _IMAGE_EXTENSIONS:
                return _inspect_image(target)
            if ext in _TEXT_EXTENSIONS or ext == "":
                return _inspect_text(target)
            return _inspect_binary(target)
        except Exception as e:
            return f"[error] Failed to inspect {file_path}: {e}"

    return file_inspect


def create_file_read_tool(project_root: str, node_name: str = "executor"):
    @tool
    def file_read(file_path: str) -> str:
        """Read a file relative to the project root. Returns the raw file contents."""
        assert_not_blacklisted(file_path)
        assert_node_access(file_path, node_name)
        target = _resolve_safe(project_root, file_path)
        if not target.exists():
            return f"[error] File not found: {file_path}"
        return target.read_text()

    return file_read


def create_file_write_tool(project_root: str, node_name: str = "executor"):
    @tool
    def file_write(file_path: str, content: str) -> str:
        """Write content to a file relative to the project root. Creates parent directories if needed."""
        assert_not_blacklisted(file_path)
        assert_node_access(file_path, node_name)
        target = _resolve_safe(project_root, file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return f"Wrote {len(content)} bytes to {file_path}"

    return file_write
