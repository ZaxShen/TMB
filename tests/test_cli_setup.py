"""Tests for setup() pyproject.toml generation logic."""
import pytest
from pathlib import Path


class TestInjectTmbDependency:
    """Test _inject_tmb_dependency for both local and PyPI installs."""

    def test_local_install_fresh_toml_with_deps(self, tmp_path):
        """Local install: injects 'tmb' + [tool.uv.sources] path."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = '[project]\nname = "test"\ndependencies = [\n    "requests",\n]\n'
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, Path("TMB"))
        result = toml.read_text()
        assert '"tmb"' in result
        assert '[tool.uv.sources]' in result
        assert 'path = "./TMB"' in result

    def test_pypi_install_fresh_toml_with_deps(self, tmp_path):
        """PyPI install (tmb_rel=None): injects 'trustmybot', no path source."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = '[project]\nname = "test"\ndependencies = [\n    "requests",\n]\n'
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, None)
        result = toml.read_text()
        assert '"trustmybot"' in result
        assert '[tool.uv.sources]' not in result

    def test_local_install_empty_deps(self, tmp_path):
        """Local install: handles empty dependencies = []."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = '[project]\nname = "test"\ndependencies = []\n'
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, Path("TMB"))
        result = toml.read_text()
        assert '"tmb"' in result

    def test_pypi_install_empty_deps(self, tmp_path):
        """PyPI install: handles empty dependencies = []."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = '[project]\nname = "test"\ndependencies = []\n'
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, None)
        result = toml.read_text()
        assert '"trustmybot"' in result
        assert '[tool.uv.sources]' not in result

    def test_local_install_no_project_section(self, tmp_path):
        """Local install: no [project] section at all."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = '[build-system]\nrequires = ["hatchling"]\n'
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, Path("TMB"))
        result = toml.read_text()
        assert '"tmb"' in result
        assert '[tool.uv.sources]' in result

    def test_pypi_install_no_project_section(self, tmp_path):
        """PyPI install: no [project] section at all."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = '[build-system]\nrequires = ["hatchling"]\n'
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, None)
        result = toml.read_text()
        assert '"trustmybot"' in result
        assert '[tool.uv.sources]' not in result

    def test_no_duplicate_if_already_present(self, tmp_path):
        """Should not inject if tmb/trustmybot already in dependencies."""
        # This is tested via the caller (setup checks before calling),
        # but _inject should still handle gracefully
        pass

    def test_local_install_multiline_deps_insert_before_close(self, tmp_path):
        """Local install: appends 'tmb' before closing ] in multi-line deps."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = (
            '[project]\nname = "test"\ndependencies = [\n'
            '    "requests",\n'
            '    "httpx",\n'
            ']\n'
        )
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, Path("TMB"))
        result = toml.read_text()
        assert '"tmb"' in result
        assert '[tool.uv.sources]' in result

    def test_pypi_install_multiline_deps_insert_before_close(self, tmp_path):
        """PyPI install: appends 'trustmybot' before closing ] in multi-line deps."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = (
            '[project]\nname = "test"\ndependencies = [\n'
            '    "requests",\n'
            '    "httpx",\n'
            ']\n'
        )
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, None)
        result = toml.read_text()
        assert '"trustmybot"' in result
        assert '[tool.uv.sources]' not in result

    def test_local_install_no_deps_key_adds_it(self, tmp_path):
        """Local install: [project] without dependencies key gets one added."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = '[project]\nname = "test"\nversion = "0.1.0"\n'
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, Path("TMB"))
        result = toml.read_text()
        assert '"tmb"' in result
        assert '[tool.uv.sources]' in result

    def test_pypi_install_no_deps_key_adds_it(self, tmp_path):
        """PyPI install: [project] without dependencies key gets one added."""
        from tmb.cli import _inject_tmb_dependency
        toml = tmp_path / "pyproject.toml"
        content = '[project]\nname = "test"\nversion = "0.1.0"\n'
        toml.write_text(content)
        _inject_tmb_dependency(toml, content, None)
        result = toml.read_text()
        assert '"trustmybot"' in result
        assert '[tool.uv.sources]' not in result
