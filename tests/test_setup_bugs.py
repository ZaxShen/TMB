"""Tests for setup bug fixes — project.yaml sentinel and package install flow."""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestIsFirstRun:
    """_is_first_run() should return False if ANY config file exists."""

    def test_first_run_no_files(self, tmp_path):
        """No config files → first run."""
        from tmb.cli import _is_first_run
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        with patch("tmb.cli.user_cfg_dir", return_value=cfg_dir):
            assert _is_first_run() is True

    def test_not_first_run_project_yaml(self, tmp_path):
        """project.yaml exists → not first run."""
        from tmb.cli import _is_first_run
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "project.yaml").write_text("name: test\n")
        with patch("tmb.cli.user_cfg_dir", return_value=cfg_dir):
            assert _is_first_run() is False

    def test_not_first_run_nodes_yaml_only(self, tmp_path):
        """nodes.yaml exists but no project.yaml → still not first run."""
        from tmb.cli import _is_first_run
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "nodes.yaml").write_text("planner:\n  model:\n    provider: ollama\n")
        with patch("tmb.cli.user_cfg_dir", return_value=cfg_dir):
            assert _is_first_run() is False

    def test_not_first_run_both_exist(self, tmp_path):
        """Both config files exist → not first run."""
        from tmb.cli import _is_first_run
        cfg_dir = tmp_path / "config"
        cfg_dir.mkdir()
        (cfg_dir / "project.yaml").write_text("name: test\n")
        (cfg_dir / "nodes.yaml").write_text("planner:\n  model:\n    provider: ollama\n")
        with patch("tmb.cli.user_cfg_dir", return_value=cfg_dir):
            assert _is_first_run() is False


class TestGetLlmImportError:
    """get_llm() should give context-appropriate install instructions."""

    def test_import_error_tool_install(self):
        """When running as a uv tool, error message should suggest uv tool install --with."""
        from tmb.config import get_llm
        mock_cfg = {
            "planner": {"model": {"provider": "ollama", "name": "llama3.2:3b", "base_url": "http://localhost:11434"}}
        }
        # Patch tmb.paths.TMB_ROOT because the except block does `from tmb.paths import TMB_ROOT`,
        # which re-imports from the paths module directly (bypassing tmb.config.TMB_ROOT binding).
        # Set up TMB_ROOT and get_project_root patches BEFORE patching importlib,
        # because mock.patch itself uses importlib.import_module to resolve targets.
        import importlib
        with patch("tmb.config.load_nodes_config", return_value=mock_cfg), \
             patch("tmb.paths.TMB_ROOT", Path("/usr/lib/python/site-packages/tmb")), \
             patch("tmb.config.get_project_root", return_value=Path("/home/user/myproject")):
            # importlib mock applied last (innermost) to avoid interfering with patch setup
            with patch.object(importlib, "import_module", side_effect=ImportError("No module")):
                with pytest.raises(ImportError, match="uv tool install --with"):
                    get_llm("planner")

    def test_import_error_local_install(self):
        """When running as local install, error message should suggest uv add."""
        from tmb.config import get_llm
        mock_cfg = {
            "planner": {"model": {"provider": "ollama", "name": "llama3.2:3b", "base_url": "http://localhost:11434"}}
        }
        import importlib
        with patch("tmb.config.load_nodes_config", return_value=mock_cfg), \
             patch("tmb.paths.TMB_ROOT", Path("/home/user/myproject/TMB")), \
             patch("tmb.config.get_project_root", return_value=Path("/home/user/myproject")):
            with patch.object(importlib, "import_module", side_effect=ImportError("No module")):
                with pytest.raises(ImportError, match="uv add"):
                    get_llm("planner")
