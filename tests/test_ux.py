"""Tests for tmb.ux — UX helper functions."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tmb.ux import open_in_editor, wait_for_file_change


# NOTE: ux.py imports `sys as _sys` and `subprocess` *locally* inside
# open_in_editor(), not at module level. There is no `tmb.ux.sys` or
# `tmb.ux.subprocess` attribute.  The correct mock targets are the
# actual module-level attributes: `sys.platform` and `subprocess.Popen`.


class TestOpenInEditor:
    def test_returns_bool(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello")
        result = open_in_editor(f)
        assert isinstance(result, bool)

    @patch("sys.platform", "darwin")
    @patch("subprocess.Popen")
    def test_macos_calls_open(self, mock_popen, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello")
        result = open_in_editor(f)
        assert result is True
        mock_popen.assert_called_once_with(["open", str(f)])

    @patch("sys.platform", "linux")
    @patch("subprocess.Popen")
    def test_linux_calls_xdg_open(self, mock_popen, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello")
        result = open_in_editor(f)
        assert result is True
        mock_popen.assert_called_once_with(["xdg-open", str(f)])

    @patch("sys.platform", "linux")
    @patch("subprocess.Popen", side_effect=FileNotFoundError("xdg-open not found"))
    def test_handles_missing_command(self, mock_popen, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello")
        result = open_in_editor(f)
        assert result is False

    @patch("sys.platform", "darwin")
    @patch("subprocess.Popen", side_effect=OSError("something broke"))
    def test_handles_os_error(self, mock_popen, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("hello")
        result = open_in_editor(f)
        assert result is False


class TestWaitForFileChange:
    def test_detects_modification(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("original")
        # Simulate a save by changing mtime after a tiny delay
        initial_mtime = os.path.getmtime(str(f))
        # Set mtime to the future to simulate save
        os.utime(str(f), (initial_mtime + 2, initial_mtime + 2))
        # Now call with very short poll — it should see the change immediately
        # But we need to set it back first, then change during the poll
        os.utime(str(f), (initial_mtime, initial_mtime))

        import threading
        def modify_later():
            time.sleep(0.3)
            f.write_text("modified")

        t = threading.Thread(target=modify_later)
        t.start()
        result = wait_for_file_change(f, timeout=5.0, poll_interval=0.1)
        t.join()
        assert result is True

    def test_timeout_returns_false(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("content")
        result = wait_for_file_change(f, timeout=0.3, poll_interval=0.1)
        assert result is False

    def test_missing_file_returns_false(self, tmp_path):
        f = tmp_path / "nonexistent.md"
        result = wait_for_file_change(f, timeout=0.3, poll_interval=0.1)
        assert result is False
