"""Shared fixtures for TMB unit tests."""

from __future__ import annotations

import pytest

from tmb.store import Store


@pytest.fixture
def store(tmp_path):
    """Store backed by a temporary SQLite file — isolated per test."""
    db = tmp_path / "test.db"
    return Store(db_path=db)


@pytest.fixture
def tmp_project(tmp_path):
    """Minimal fake project directory with required config files."""
    cfg_dir = tmp_path / ".tmb" / "config"
    cfg_dir.mkdir(parents=True)

    docs_dir = tmp_path / "bro"
    docs_dir.mkdir()

    (cfg_dir / "project.yaml").write_text(
        "name: test-project\ntest_command: pytest\nmax_retry_per_task: 3\n"
    )

    return tmp_path
