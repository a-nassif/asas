import subprocess

import pytest
import tomlkit

from asas_cli.registry import PACKAGES
from asas_cli.scaffold import scaffold


def _fake_run_pinned_tag(*args, **kwargs):
    return subprocess.CompletedProcess(args, 0, stdout="aaa\trefs/tags/v0.15.0\n", stderr="")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    # Every test pins an explicit tag, so `latest_tag()` should never
    # actually run — this fixture just guarantees that if it did, it
    # wouldn't hit the network from inside a test.
    monkeypatch.setattr(subprocess, "run", _fake_run_pinned_tag)


def test_scaffold_creates_expected_files(tmp_path):
    project_dir = tmp_path / "demo"
    created = scaffold(project_dir, "demo", ["lookups", "ratelimit"], tag="v0.15.0")

    names = {p.name for p in created}
    assert names == {"main.py", "settings.py", "pyproject.toml", "README.md", ".env.example"}
    for path in created:
        assert path.exists()


def test_refuses_to_scaffold_into_nonempty_dir(tmp_path):
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "existing.txt").write_text("don't touch me")

    with pytest.raises(FileExistsError):
        scaffold(project_dir, "demo", ["lookups"], tag="v0.15.0")

    assert (project_dir / "existing.txt").read_text() == "don't touch me"


@pytest.mark.parametrize("key", sorted(PACKAGES))
def test_generated_main_py_is_syntactically_valid_for_every_package(tmp_path, key):
    project_dir = tmp_path / key
    scaffold(project_dir, "demo", [key], tag="v0.15.0")
    compile((project_dir / "main.py").read_text(), "main.py", "exec")
    compile((project_dir / "settings.py").read_text(), "settings.py", "exec")


def test_generated_main_py_is_valid_for_all_packages_combined(tmp_path):
    project_dir = tmp_path / "everything"
    scaffold(project_dir, "demo", sorted(PACKAGES), tag="v0.15.0")
    compile((project_dir / "main.py").read_text(), "main.py", "exec")


def test_pyproject_toml_pins_selected_packages_at_given_tag(tmp_path):
    project_dir = tmp_path / "demo"
    scaffold(project_dir, "demo", ["lookups", "ratelimit"], tag="v0.15.0")
    doc = tomlkit.parse((project_dir / "pyproject.toml").read_text())
    deps = "\n".join(doc["project"]["dependencies"])
    assert "asas-lookups" in deps and "v0.15.0" in deps
    assert "asas-ratelimit" in deps


def test_settings_py_includes_ratelimit_fields_only_when_selected(tmp_path):
    with_rl = tmp_path / "with_rl"
    without_rl = tmp_path / "without_rl"
    scaffold(with_rl, "demo", ["ratelimit"], tag="v0.15.0")
    scaffold(without_rl, "demo", ["lookups"], tag="v0.15.0")

    assert "rate_limit_enabled" in (with_rl / "settings.py").read_text()
    assert "rate_limit_enabled" not in (without_rl / "settings.py").read_text()


def test_mcp_project_name_is_substituted_not_left_literal(tmp_path):
    project_dir = tmp_path / "myservice"
    scaffold(project_dir, "myservice", ["mcp"], tag="v0.15.0")
    main_py = (project_dir / "main.py").read_text()
    assert 'name="myservice"' in main_py
    assert "{project_name}" not in main_py


def test_readme_lists_wired_packages_and_pinned_tag(tmp_path):
    project_dir = tmp_path / "demo"
    scaffold(project_dir, "demo", ["lookups"], tag="v0.15.0")
    readme = (project_dir / "README.md").read_text()
    assert "asas-lookups" in readme
    assert "v0.15.0" in readme
