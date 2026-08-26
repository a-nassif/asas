import subprocess

import pytest
import tomlkit

from asas_cli.cli import main


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="aaa\trefs/tags/v0.15.0\n", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)


def test_list_command_runs_clean(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "lookups" in out
    assert "asas-ratelimit" not in out  # lists short keys, not dist names


def test_add_command_writes_pin(tmp_path, capsys):
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "demo"\ndependencies = []\n')

    rc = main(["add", "ratelimit", "--tag", "v0.15.0", "--path", str(path)])

    assert rc == 0
    assert "added asas-ratelimit" in capsys.readouterr().out
    doc = tomlkit.parse(path.read_text())
    assert any("asas-ratelimit" in d for d in doc["project"]["dependencies"])


def test_add_unknown_package_fails_cleanly(tmp_path, capsys):
    path = tmp_path / "pyproject.toml"
    path.write_text('[project]\nname = "demo"\ndependencies = []\n')

    rc = main(["add", "nope", "--path", str(path)])

    assert rc == 1
    assert "unknown Asas package" in capsys.readouterr().err


def test_new_command_scaffolds_project(tmp_path, capsys):
    rc = main(["new", "demo", "--with", "lookups,ratelimit", "--tag", "v0.15.0", "--dir", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / "demo" / "main.py").exists()
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

    rc = main(["new", "demo", "--with", "lookups", "--tag", "v0.15.0", "--dir", str(tmp_path)])

    assert rc == 1
    assert "already exists" in capsys.readouterr().err
    assert (project_dir / "keep.txt").exists()
