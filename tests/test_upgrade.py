"""Tests for upgrade/uninstall functions in tmb/cli.py.

Tests cover:
  - _detect_install_info(): returns {channel, branch, method}
  - upgrade(force_stable): auto-upgrade for all channels
  - uninstall(): confirm + run the right uninstall command
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch, call

import pytest

from tmb.cli import _detect_install_info, upgrade, uninstall


# ── Helpers ──────────────────────────────────────────────────────────────────

def _mock_dist(raw_text):
    """Create a mock distribution whose read_text returns raw_text."""
    dist = MagicMock()
    dist.read_text.return_value = raw_text
    return dist


def _mock_run_result(returncode=0, stdout="", stderr=""):
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def _brew_not_found(*args, **kwargs):
    """Side effect: brew list returns non-zero (not a brew install)."""
    return _mock_run_result(returncode=1)


# ── TestDetectInstallInfo ────────────────────────────────────────────────────

class TestDetectInstallInfo:
    """Tests for _detect_install_info() — returns {channel, branch, method}."""

    def test_detect_brew(self):
        """brew list trustmybot returns 0 → brew channel."""
        brew_ok = _mock_run_result(returncode=0)
        with patch("tmb.cli.subprocess.run", return_value=brew_ok):
            info = _detect_install_info()
        assert info == {"channel": "brew", "branch": None, "method": "brew"}

    def test_detect_git_with_branch(self):
        """PEP 610 with vcs_info → git channel with branch name."""
        payload = json.dumps({
            "url": "https://github.com/ZaxShen/TMB",
            "vcs_info": {"requested_revision": "dev"},
        })
        with patch("tmb.cli.subprocess.run", side_effect=_brew_not_found), \
             patch("importlib.metadata.distribution", return_value=_mock_dist(payload)), \
             patch("shutil.which", return_value="/usr/local/bin/uv"):
            info = _detect_install_info()
        assert info["channel"] == "git"
        assert info["branch"] == "dev"
        assert info["method"] == "uv_tool"

    def test_detect_git_feature_branch(self):
        """Git install from a feature branch (not just dev)."""
        payload = json.dumps({
            "url": "https://github.com/ZaxShen/TMB",
            "vcs_info": {"requested_revision": "feature-x"},
        })
        with patch("tmb.cli.subprocess.run", side_effect=_brew_not_found), \
             patch("importlib.metadata.distribution", return_value=_mock_dist(payload)), \
             patch("shutil.which", return_value="/usr/local/bin/uv"):
            info = _detect_install_info()
        assert info["channel"] == "git"
        assert info["branch"] == "feature-x"

    def test_detect_stable_pypi(self):
        """No direct_url.json → stable channel."""
        with patch("tmb.cli.subprocess.run", side_effect=_brew_not_found), \
             patch("importlib.metadata.distribution", return_value=_mock_dist(None)), \
             patch("shutil.which", return_value="/usr/local/bin/uv"):
            info = _detect_install_info()
        assert info == {"channel": "stable", "branch": None, "method": "uv_tool"}

    def test_detect_editable(self):
        """PEP 610 with dir_info.editable → editable channel."""
        payload = json.dumps({
            "url": "file:///Users/dev/TMB",
            "dir_info": {"editable": True},
        })
        with patch("tmb.cli.subprocess.run", side_effect=_brew_not_found), \
             patch("importlib.metadata.distribution", return_value=_mock_dist(payload)):
            info = _detect_install_info()
        assert info == {"channel": "editable", "branch": None, "method": "editable"}

    def test_detect_pip_fallback(self):
        """No uv available → method is pip."""
        with patch("tmb.cli.subprocess.run", side_effect=_brew_not_found), \
             patch("importlib.metadata.distribution", return_value=_mock_dist(None)), \
             patch("shutil.which", return_value=None):
            info = _detect_install_info()
        assert info["channel"] == "stable"
        assert info["method"] == "pip"

    def test_detect_brew_check_catches_file_not_found(self):
        """brew not installed (FileNotFoundError) → falls through to PEP 610."""
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("brew not found")
        with patch("tmb.cli.subprocess.run", side_effect=raise_fnf), \
             patch("importlib.metadata.distribution", return_value=_mock_dist(None)), \
             patch("shutil.which", return_value="/usr/local/bin/uv"):
            info = _detect_install_info()
        assert info["channel"] == "stable"

    def test_detect_handles_metadata_exception(self):
        """importlib.metadata failure → falls back to stable."""
        import importlib.metadata as _im
        with patch("tmb.cli.subprocess.run", side_effect=_brew_not_found), \
             patch("importlib.metadata.distribution", side_effect=_im.PackageNotFoundError("x")), \
             patch("shutil.which", return_value="/usr/local/bin/uv"):
            info = _detect_install_info()
        assert info["channel"] == "stable"


# ── TestUpgrade ──────────────────────────────────────────────────────────────

class TestUpgrade:
    """Tests for upgrade(force_stable) — auto-upgrades for all channels."""

    def test_upgrade_stable_uv(self, capsys):
        """Stable/uv_tool: runs uv tool upgrade trustmybot."""
        uv_result = _mock_run_result(returncode=0)
        ver_result = _mock_run_result(returncode=0, stdout="Trust Me Bro v0.5.7")

        with patch("tmb.cli._detect_install_info", return_value={"channel": "stable", "branch": None, "method": "uv_tool"}), \
             patch("importlib.metadata.version", return_value="0.5.6"), \
             patch("tmb.cli.subprocess.run", side_effect=[uv_result, ver_result]) as mock_run:
            upgrade()

        first_call = mock_run.call_args_list[0][0][0]
        assert first_call == ["uv", "tool", "upgrade", "trustmybot"]

    def test_upgrade_brew(self, capsys):
        """Brew channel: runs brew upgrade trustmybot."""
        brew_result = _mock_run_result(returncode=0)
        ver_result = _mock_run_result(returncode=0, stdout="Trust Me Bro v0.5.7")

        with patch("tmb.cli._detect_install_info", return_value={"channel": "brew", "branch": None, "method": "brew"}), \
             patch("importlib.metadata.version", return_value="0.5.6"), \
             patch("tmb.cli.subprocess.run", side_effect=[brew_result, ver_result]) as mock_run:
            upgrade()

        first_call = mock_run.call_args_list[0][0][0]
        assert first_call == ["brew", "upgrade", "trustmybot"]

    def test_upgrade_git_dev(self, capsys):
        """Git/dev: runs uv tool install from git+...@dev."""
        git_result = _mock_run_result(returncode=0)
        ver_result = _mock_run_result(returncode=0, stdout="Trust Me Bro v0.5.7")

        with patch("tmb.cli._detect_install_info", return_value={"channel": "git", "branch": "dev", "method": "uv_tool"}), \
             patch("importlib.metadata.version", return_value="0.5.6"), \
             patch("tmb.cli.subprocess.run", side_effect=[git_result, ver_result]) as mock_run:
            upgrade()

        first_call = mock_run.call_args_list[0][0][0]
        assert "git+https://github.com/ZaxShen/TMB@dev" in first_call

    def test_upgrade_force_stable_overrides_git(self, capsys):
        """force_stable=True: runs stable upgrade even when channel is git."""
        uv_result = _mock_run_result(returncode=0)
        ver_result = _mock_run_result(returncode=0, stdout="Trust Me Bro v0.5.7")

        with patch("tmb.cli._detect_install_info", return_value={"channel": "git", "branch": "dev", "method": "uv_tool"}), \
             patch("importlib.metadata.version", return_value="0.5.6"), \
             patch("tmb.cli.subprocess.run", side_effect=[uv_result, ver_result]) as mock_run:
            upgrade(force_stable=True)

        first_call = mock_run.call_args_list[0][0][0]
        assert first_call == ["uv", "tool", "upgrade", "trustmybot"]

    def test_upgrade_editable(self, capsys):
        """Editable install: prints git pull message, no subprocess."""
        with patch("tmb.cli._detect_install_info", return_value={"channel": "editable", "branch": None, "method": "editable"}), \
             patch("importlib.metadata.version", return_value="0.5.6"), \
             patch("tmb.cli.subprocess.run") as mock_run:
            upgrade()

        mock_run.assert_not_called()
        out = capsys.readouterr().out
        assert "git pull" in out

    def test_upgrade_shows_current_version(self, capsys):
        """Output includes the current version number."""
        uv_result = _mock_run_result(returncode=0)
        ver_result = _mock_run_result(returncode=0, stdout="Trust Me Bro v0.5.7")

        with patch("tmb.cli._detect_install_info", return_value={"channel": "stable", "branch": None, "method": "uv_tool"}), \
             patch("importlib.metadata.version", return_value="0.5.6"), \
             patch("tmb.cli.subprocess.run", side_effect=[uv_result, ver_result]):
            upgrade()

        out = capsys.readouterr().out
        assert "0.5.6" in out

    def test_upgrade_already_latest(self, capsys):
        """Same version before/after → 'Already on the latest version'."""
        uv_result = _mock_run_result(returncode=0)
        ver_result = _mock_run_result(returncode=0, stdout="Trust Me Bro v0.5.6")

        with patch("tmb.cli._detect_install_info", return_value={"channel": "stable", "branch": None, "method": "uv_tool"}), \
             patch("importlib.metadata.version", return_value="0.5.6"), \
             patch("tmb.cli.subprocess.run", side_effect=[uv_result, ver_result]):
            upgrade()

        out = capsys.readouterr().out
        assert "latest" in out.lower()

    def test_upgrade_git_branch_gone_switch_to_stable(self, capsys):
        """Git branch deleted → prompts user → switches to stable."""
        fail_result = _mock_run_result(returncode=1, stderr="failed to fetch branch")
        uv_result = _mock_run_result(returncode=0)
        ver_result = _mock_run_result(returncode=0, stdout="Trust Me Bro v0.5.7")

        with patch("tmb.cli._detect_install_info", return_value={"channel": "git", "branch": "feature-x", "method": "uv_tool"}), \
             patch("importlib.metadata.version", return_value="0.5.6"), \
             patch("tmb.cli.subprocess.run", side_effect=[fail_result, uv_result, ver_result]) as mock_run, \
             patch("builtins.input", return_value="y"):
            upgrade()

        out = capsys.readouterr().out
        assert "feature-x" in out
        # Should have called stable upgrade after the git failure
        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["uv", "tool", "upgrade", "trustmybot"] in calls or \
               any("--upgrade" in c and "--force" in c for c in calls)


# ── TestUninstall ────────────────────────────────────────────────────────────

class TestUninstall:
    """Tests for uninstall() — confirm + run the right command."""

    def test_uninstall_uv_confirmed(self, capsys):
        """Confirmed uv_tool uninstall: runs uv tool uninstall trustmybot."""
        result = _mock_run_result(returncode=0)
        with patch("tmb.cli._detect_install_info", return_value={"channel": "stable", "branch": None, "method": "uv_tool"}), \
             patch("builtins.input", return_value="y"), \
             patch("tmb.cli.subprocess.run", return_value=result) as mock_run:
            uninstall()

        mock_run.assert_called_once()
        assert mock_run.call_args[0][0] == ["uv", "tool", "uninstall", "trustmybot"]

    def test_uninstall_cancelled(self, capsys):
        """User says 'n' → no subprocess called."""
        with patch("tmb.cli._detect_install_info", return_value={"channel": "stable", "branch": None, "method": "uv_tool"}), \
             patch("builtins.input", return_value="n"), \
             patch("tmb.cli.subprocess.run") as mock_run:
            uninstall()

        mock_run.assert_not_called()
        out = capsys.readouterr().out
        assert "Cancelled" in out

    def test_uninstall_default_no(self, capsys):
        """Empty input (default N) → no uninstall."""
        with patch("tmb.cli._detect_install_info", return_value={"channel": "stable", "branch": None, "method": "uv_tool"}), \
             patch("builtins.input", return_value=""), \
             patch("tmb.cli.subprocess.run") as mock_run:
            uninstall()

        mock_run.assert_not_called()

    def test_uninstall_brew_cleans_both(self, capsys):
        """Brew uninstall: runs both brew uninstall and uv tool uninstall."""
        result = _mock_run_result(returncode=0)
        with patch("tmb.cli._detect_install_info", return_value={"channel": "brew", "branch": None, "method": "brew"}), \
             patch("builtins.input", return_value="y"), \
             patch("tmb.cli.subprocess.run", return_value=result) as mock_run:
            uninstall()

        calls = [c[0][0] for c in mock_run.call_args_list]
        assert ["brew", "uninstall", "trustmybot"] in calls
        assert ["uv", "tool", "uninstall", "trustmybot"] in calls

    def test_uninstall_keyboard_interrupt(self, capsys):
        """Ctrl+C during confirmation → cancelled gracefully."""
        with patch("tmb.cli._detect_install_info", return_value={"channel": "stable", "branch": None, "method": "uv_tool"}), \
             patch("builtins.input", side_effect=KeyboardInterrupt), \
             patch("tmb.cli.subprocess.run") as mock_run:
            uninstall()

        mock_run.assert_not_called()

    def test_uninstall_editable(self, capsys):
        """Editable install: prints manual instruction, no subprocess."""
        with patch("tmb.cli._detect_install_info", return_value={"channel": "editable", "branch": None, "method": "editable"}), \
             patch("builtins.input", return_value="y"), \
             patch("tmb.cli.subprocess.run") as mock_run:
            uninstall()

        mock_run.assert_not_called()
        out = capsys.readouterr().out
        assert "pip uninstall" in out
