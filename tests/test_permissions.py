"""Tests for tmb.permissions — blacklist, node access, write allowlist."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


_TEST_BLACKLIST = [".env", ".env.*", "**/.env", "**/secrets/**", "TMB/**"]


@pytest.fixture(autouse=True)
def _mock_config():
    with patch(
        "tmb.permissions.load_project_config",
        return_value={"blacklist": _TEST_BLACKLIST},
    ):
        yield


def test_blacklisted_env():
    from tmb.permissions import is_blacklisted

    assert is_blacklisted("project/.env") is True
    assert is_blacklisted("project/.env.local") is True


def test_blacklisted_tmb():
    from tmb.permissions import is_blacklisted

    assert is_blacklisted("TMB/tmb/cli.py") is True


def test_not_blacklisted_normal_file():
    from tmb.permissions import is_blacklisted

    assert is_blacklisted("src/main.py") is False
    assert is_blacklisted("bro/GOALS.md") is False


def test_assert_not_blacklisted_raises():
    from tmb.permissions import assert_not_blacklisted

    with pytest.raises(PermissionError):
        assert_not_blacklisted("project/.env")


def test_node_access_planner_can_read_goals():
    from tmb.permissions import assert_node_access

    assert_node_access("bro/GOALS.md", "planner")


def test_node_access_executor_cannot_read_goals():
    from tmb.permissions import assert_node_access

    with pytest.raises(PermissionError):
        assert_node_access("GOALS.md", "executor")


def test_tmb_write_allowed_docs(tmp_path):
    from tmb.permissions import assert_tmb_write

    docs = tmp_path / "bro"
    docs.mkdir()

    with patch("tmb.permissions.docs_dir", return_value=docs):
        assert_tmb_write(docs / "BLUEPRINT.md")
        assert_tmb_write(docs / "EXECUTION.md")


def test_tmb_write_blocked_random_file(tmp_path):
    from tmb.permissions import assert_tmb_write

    docs = tmp_path / "bro"
    docs.mkdir()

    with patch("tmb.permissions.docs_dir", return_value=docs):
        with pytest.raises(PermissionError):
            assert_tmb_write(docs / "random.txt")


def test_evolve_context():
    from tmb.permissions import evolve_context, is_evolve_mode

    assert is_evolve_mode() is False

    with evolve_context():
        assert is_evolve_mode() is True

    assert is_evolve_mode() is False
