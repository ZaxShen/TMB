"""Tests for tmb.git — TMB's internal git helper module."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tmb.git import (
    has_git_binary,
    ensure_repo,
    snapshot,
    get_diff_summary,
    build_commit_message,
)


def _init_git_repo(path: Path):
    """Helper: initialize a git repo with required config in a temp dir."""
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path), capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path), capture_output=True, check=True,
    )


class TestHasGitBinary:
    def test_returns_bool(self):
        result = has_git_binary()
        assert isinstance(result, bool)

    def test_true_when_git_available(self):
        # git is available in the test environment
        assert has_git_binary() is True

    def test_false_when_git_missing(self):
        with patch("tmb.git.shutil.which", return_value=None):
            assert has_git_binary() is False


class TestEnsureRepo:
    def test_creates_git_repo_in_empty_dir(self, tmp_path):
        assert ensure_repo(tmp_path) is True
        assert (tmp_path / ".git").is_dir()

    def test_creates_gitignore_if_missing(self, tmp_path):
        ensure_repo(tmp_path)
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert ".env" in content
        assert "__pycache__/" in content
        assert ".tmb/" in content

    def test_preserves_existing_gitignore(self, tmp_path):
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("my_custom_ignore\n")
        ensure_repo(tmp_path)
        assert gitignore.read_text() == "my_custom_ignore\n"

    def test_uses_existing_repo(self, tmp_path):
        """If already inside a git repo, don't create nested repo."""
        _init_git_repo(tmp_path)
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        result = ensure_repo(subdir)
        assert result is True
        assert not (subdir / ".git").is_dir()  # no nested repo

    def test_returns_false_when_git_missing(self, tmp_path):
        with patch("tmb.git.has_git_binary", return_value=False):
            assert ensure_repo(tmp_path) is False

    def test_idempotent(self, tmp_path):
        """Calling ensure_repo twice is safe."""
        assert ensure_repo(tmp_path) is True
        assert ensure_repo(tmp_path) is True


class TestSnapshot:
    def test_creates_commit_returns_hash(self, tmp_path):
        _init_git_repo(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        result = snapshot(tmp_path, "test commit")
        assert result is not None
        assert len(result) >= 7  # short hash

    def test_returns_none_when_nothing_to_commit(self, tmp_path):
        _init_git_repo(tmp_path)
        # Need an initial commit first (can't have truly empty repo)
        (tmp_path / "init.txt").write_text("init")
        snapshot(tmp_path, "initial")
        # Now nothing changed
        result = snapshot(tmp_path, "should be none")
        assert result is None

    def test_returns_none_when_git_missing(self, tmp_path):
        with patch("tmb.git.has_git_binary", return_value=False):
            result = snapshot(tmp_path, "test")
            assert result is None

    def test_commit_message_matches(self, tmp_path):
        _init_git_repo(tmp_path)
        (tmp_path / "file.txt").write_text("hello")
        snapshot(tmp_path, "my custom message")
        result = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        assert result.stdout.strip() == "my custom message"


class TestGetDiffSummary:
    def test_detects_new_file(self, tmp_path):
        _init_git_repo(tmp_path)
        # Need initial commit
        (tmp_path / "init.txt").write_text("init")
        snapshot(tmp_path, "initial")
        # Add new file
        (tmp_path / "new.txt").write_text("new content")
        summary = get_diff_summary(tmp_path)
        paths = [s["path"] for s in summary]
        assert "new.txt" in paths

    def test_detects_modified_file(self, tmp_path):
        _init_git_repo(tmp_path)
        (tmp_path / "file.txt").write_text("original")
        snapshot(tmp_path, "initial")
        (tmp_path / "file.txt").write_text("modified")
        summary = get_diff_summary(tmp_path)
        paths = [s["path"] for s in summary]
        assert "file.txt" in paths

    def test_empty_when_clean(self, tmp_path):
        _init_git_repo(tmp_path)
        (tmp_path / "file.txt").write_text("content")
        snapshot(tmp_path, "initial")
        summary = get_diff_summary(tmp_path)
        assert summary == []

    def test_returns_empty_list_when_git_missing(self, tmp_path):
        with patch("tmb.git.has_git_binary", return_value=False):
            assert get_diff_summary(tmp_path) == []


class TestBuildCommitMessage:
    def test_basic_format(self):
        tasks = [
            {"branch_id": "1", "title": "Add auth module"},
            {"branch_id": "2", "title": "Write tests"},
        ]
        diff = [
            {"path": "src/auth.py", "status": "added"},
            {"path": "tests/test_auth.py", "status": "added"},
        ]
        msg = build_commit_message(42, "Implement authentication", tasks, diff)
        assert "tmb: Issue #42" in msg
        assert "Implement authentication" in msg
        assert "[1] Add auth module" in msg
        assert "[2] Write tests" in msg
        assert "src/auth.py (added)" in msg
        assert "tests/test_auth.py (added)" in msg

    def test_no_tasks(self):
        diff = [{"path": "file.txt", "status": "modified"}]
        msg = build_commit_message(1, "Quick fix", [], diff)
        assert "tmb: Issue #1" in msg
        assert "Tasks completed" not in msg
        assert "file.txt (modified)" in msg

    def test_no_diff(self):
        tasks = [{"branch_id": "1", "title": "Do something"}]
        msg = build_commit_message(1, "Something", tasks, [])
        assert "tmb: Issue #1" in msg
        assert "[1] Do something" in msg
        assert "Files changed" not in msg

    def test_truncates_long_objective(self):
        long_obj = "A" * 200
        msg = build_commit_message(1, long_obj, [], [])
        first_line = msg.split("\n")[0]
        assert len(first_line) < 120  # reasonable first-line length
