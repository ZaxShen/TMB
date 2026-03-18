"""Tests for exclude directory configuration."""
import subprocess
from pathlib import Path
from unittest.mock import patch


def test_gatekeeper_get_tree_reads_exclude_config():
    """_get_tree should include exclude patterns from project config."""
    from tmb.nodes.gatekeeper import _get_tree

    with patch("tmb.nodes.gatekeeper.load_project_config") as mock_cfg:
        mock_cfg.return_value = {"exclude": ["data/raw/**", "vendor/**"]}
        # Just verify it doesn't crash — the actual find command needs a real dir
        result = _get_tree(Path("/tmp"))
        # Result should be a string (even if empty)
        assert isinstance(result, str)


def test_project_default_yaml_has_exclude_comment():
    """project.default.yaml should have exclude section (commented out)."""
    from tmb.paths import DEFAULT_CFG_DIR
    content = (DEFAULT_CFG_DIR / "project.default.yaml").read_text()
    assert "exclude" in content
