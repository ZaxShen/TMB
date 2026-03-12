"""Tests for gatekeeper node — deterministic context gathering."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def _make_gatekeeper_patches(tmp_path, config_name, file_registry_count=0,
                              scan_context=None):
    """Build the patch stack for gatekeeper tests."""
    fake_config = {"name": config_name}
    fake_store = MagicMock()
    fake_store.file_registry_count.return_value = file_registry_count

    patches = [
        patch("tmb.nodes.gatekeeper.load_project_config", return_value=fake_config),
        patch("tmb.nodes.gatekeeper.get_project_root", return_value=tmp_path),
        patch("tmb.store.Store", return_value=fake_store),
    ]
    if scan_context is not None:
        patches.append(
            patch("tmb.scanner.build_project_context_from_scan",
                  return_value=scan_context)
        )
    return patches


def test_gatekeeper_scans_project(tmp_path):
    """Gatekeeper should produce project_context with directory tree and key files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "README.md").write_text("# My Project\nA test project.")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

    patches = _make_gatekeeper_patches(tmp_path, "test-project")
    with patches[0], patches[1], patches[2]:
        from tmb.nodes.gatekeeper import gatekeeper
        result = gatekeeper({"objective": "test"})

    ctx = result["project_context"]
    assert "test-project" in ctx
    assert "README.md" in ctx
    assert "My Project" in ctx
    assert "pyproject.toml" in ctx


def test_gatekeeper_handles_empty_project(tmp_path):
    """Gatekeeper should work even with an empty directory."""
    patches = _make_gatekeeper_patches(tmp_path, "empty-project")
    with patches[0], patches[1], patches[2]:
        from tmb.nodes.gatekeeper import gatekeeper
        result = gatekeeper({"objective": "test"})

    ctx = result["project_context"]
    assert "empty-project" in ctx
    assert "no key files found" in ctx


def test_gatekeeper_enriches_with_scan_data(tmp_path):
    """Gatekeeper should include file registry data when available."""
    (tmp_path / "README.md").write_text("# Scanned project")

    scan_text = "## Tech Stack\npython, typescript\n## File Summary\n42 files"
    patches = _make_gatekeeper_patches(
        tmp_path, "scanned-project",
        file_registry_count=42,
        scan_context=scan_text,
    )
    with patches[0], patches[1], patches[2], patches[3]:
        from tmb.nodes.gatekeeper import gatekeeper
        result = gatekeeper({"objective": "test"})

    ctx = result["project_context"]
    assert "Tech Stack" in ctx
    assert "42 files" in ctx


def test_tree_excludes_git_and_pyc(tmp_path):
    """_get_tree should skip .git dirs and .pyc files."""
    from tmb.nodes.gatekeeper import _get_tree

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print(1)")
    (tmp_path / "src" / "app.pyc").write_text("bytecode")

    tree = _get_tree(tmp_path)

    # .git content should be excluded
    assert "config" not in tree or ".git/config" not in tree
    assert ".pyc" not in tree
    assert "app.py" in tree


def test_tree_includes_source_files(tmp_path):
    """_get_tree should include normal source files."""
    from tmb.nodes.gatekeeper import _get_tree

    (tmp_path / "main.py").write_text("print(1)")
    (tmp_path / "lib").mkdir()
    (tmp_path / "lib" / "utils.py").write_text("def helper(): pass")

    tree = _get_tree(tmp_path)

    assert "main.py" in tree
    assert "utils.py" in tree


def test_read_key_files_content(tmp_path):
    """_read_key_files should read README.md and pyproject.toml content."""
    from tmb.nodes.gatekeeper import _read_key_files

    (tmp_path / "README.md").write_text("# Hello\nThis is a readme.")
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'test'")

    content = _read_key_files(tmp_path)

    assert "README.md" in content
    assert "Hello" in content
    assert "pyproject.toml" in content


def test_read_key_files_truncation(tmp_path):
    """_read_key_files should truncate files exceeding _MAX_FILE_PREVIEW."""
    from tmb.nodes.gatekeeper import _read_key_files, _MAX_FILE_PREVIEW

    (tmp_path / "README.md").write_text("x" * (_MAX_FILE_PREVIEW + 1000))

    content = _read_key_files(tmp_path)
    assert len(content) < _MAX_FILE_PREVIEW + 500
