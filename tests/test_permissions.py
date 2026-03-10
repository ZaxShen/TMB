"""Tests for baymax.permissions — blacklist, node access, write allowlist."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


_TEST_BLACKLIST = [".env", ".env.*", "**/.env", "**/secrets/**", "Baymax/**"]


@pytest.fixture(autouse=True)
def _mock_config():
    with patch(
        "baymax.permissions.load_project_config",
        return_value={"blacklist": _TEST_BLACKLIST},
    ):
        yield


def test_blacklisted_env():
    from baymax.permissions import is_blacklisted

    assert is_blacklisted("project/.env") is True
    assert is_blacklisted("project/.env.local") is True


def test_blacklisted_baymax():
    from baymax.permissions import is_blacklisted

    assert is_blacklisted("Baymax/baymax/cli.py") is True


def test_not_blacklisted_normal_file():
    from baymax.permissions import is_blacklisted

    assert is_blacklisted("src/main.py") is False
    assert is_blacklisted("baymax-docs/GOALS.md") is False


def test_assert_not_blacklisted_raises():
    from baymax.permissions import assert_not_blacklisted

    with pytest.raises(PermissionError):
        assert_not_blacklisted("project/.env")


def test_node_access_planner_can_read_goals():
    from baymax.permissions import assert_node_access

    assert_node_access("baymax-docs/GOALS.md", "planner")


def test_node_access_executor_cannot_read_goals():
    from baymax.permissions import assert_node_access

    with pytest.raises(PermissionError):
        assert_node_access("GOALS.md", "executor")


def test_baymax_write_allowed_docs(tmp_path):
    from baymax.permissions import assert_baymax_write

    docs = tmp_path / "baymax-docs"
    docs.mkdir()

    with patch("baymax.permissions.docs_dir", return_value=docs):
        assert_baymax_write(docs / "BLUEPRINT.md")
        assert_baymax_write(docs / "EXECUTION.md")


def test_baymax_write_blocked_random_file(tmp_path):
    from baymax.permissions import assert_baymax_write

    docs = tmp_path / "baymax-docs"
    docs.mkdir()

    with patch("baymax.permissions.docs_dir", return_value=docs):
        with pytest.raises(PermissionError):
            assert_baymax_write(docs / "random.txt")


def test_evolve_context():
    from baymax.permissions import evolve_context, is_evolve_mode

    assert is_evolve_mode() is False

    with evolve_context():
        assert is_evolve_mode() is True

    assert is_evolve_mode() is False
