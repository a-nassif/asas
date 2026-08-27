import subprocess

import pytest
import tomlkit

from asas_cli.cli import main

_LS_REMOTE_OUTPUT = (
    "abc\trefs/tags/asas-lookups/v0.11.0\n"
    "def\trefs/tags/asas-ratelimit/v0.11.0\n"
)


@pytest.fixture(autouse=True)
def _fake_remote(monkeypatch):
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=_LS_REMOTE_OUTPUT, stderr="")

    monkeypatch.setattr(subprocess, "run", _run)


def test_list_command_runs_clean(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "lookups" in out
    assert "asas-ratelimit" not in out  # lists short keys, not dist names


def test_add_command_writes_pin_at_latest_by_default(tmp_path, capsys):
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "demo"\ndependencies = []\n')

    rc = main(["add", "ratelimit", "--path", str(path)])

    assert rc == 0
    assert "added asas-ratelimit @ asas-ratelimit/v0.11.0" in capsys.readouterr().out
    doc = tomlkit.parse(path.read_text())
    assert any("asas-ratelimit/v0.11.0" in d for d in doc["project"]["dependencies"])


def test_add_command_respects_explicit_version(tmp_path, capsys):
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "demo"\ndependencies = []\n')

    rc = main(["add", "ratelimit", "--version", "0.9.0", "--path", str(path)])

    assert rc == 0
    doc = tomlkit.parse(path.read_text())
    deps = "\n".join(doc["project"]["dependencies"])
    assert "asas-ratelimit/v0.9.0" in deps
    assert "asas-ratelimit/v0.11.0" not in deps  # the live tag was never consulted


def test_add_unknown_package_fails_cleanly(tmp_path, capsys):
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "demo"\ndependencies = []\n')

    rc = main(["add", "nope", "--path", str(path)])

    assert rc == 1
    assert "unknown Asas package" in capsys.readouterr().err


def test_new_command_scaffolds_project_with_per_package_tags(tmp_path, capsys):
    rc = main(["new", "demo", "--with", "lookups,ratelimit", "--dir", str(tmp_path)])

    assert rc == 0
    main_py = (tmp_path / "demo" / "main.py").read_text()
    assert "import asas_lookups" in main_py and "import asas_ratelimit" in main_py
    doc = tomlkit.parse((tmp_path / "demo" / "pyproject.toml").read_text())
    deps = "\n".join(doc["project"]["dependencies"])
    assert "asas-lookups/v0.11.0" in deps
    assert "asas-ratelimit/v0.11.0" in deps
    assert "scaffolded demo" in capsys.readouterr().out


def test_new_command_rejects_unknown_package(tmp_path, capsys):
    rc = main(["new", "demo", "--with", "lookups,nope", "--dir", str(tmp_path)])

    assert rc == 1
    assert "unknown package" in capsys.readouterr().err
    assert not (tmp_path / "demo").exists()


def test_new_command_refuses_existing_nonempty_dir(tmp_path, capsys):
    project_dir = tmp_path / "demo"
    project_dir.mkdir()
    (project_dir / "keep.txt").write_text("keep")

    rc = main(["new", "demo", "--with", "lookups", "--dir", str(tmp_path)])

    assert rc == 1
    assert "already exists" in capsys.readouterr().err
    assert (project_dir / "keep.txt").exists()
