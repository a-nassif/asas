import subprocess

import pytest

from asas_cli.git_tags import FALLBACK_TAG, latest_tag

_LS_REMOTE_OUTPUT = (
    "abc123\trefs/tags/v0.1.0\n"
    "def456\trefs/tags/v0.10.0\n"
    "aaa111\trefs/tags/v0.15.0\n"
    "aaa111\trefs/tags/v0.15.0^{}\n"  # peeled annotated-tag ref, same tag
    "zzz999\trefs/tags/not-a-version\n"
)


def _fake_run(output):
    def _run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    return _run


def test_latest_tag_picks_highest_semver(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run(_LS_REMOTE_OUTPUT))
    assert latest_tag() == "v0.15.0"


def test_latest_tag_ignores_non_semver_refs(monkeypatch):
    monkeypatch.setattr(subprocess, "run", _fake_run("abc\trefs/tags/not-a-version\n"))
    assert latest_tag() == FALLBACK_TAG


def test_latest_tag_falls_back_when_git_unavailable(monkeypatch, capsys):
    def _raise(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(subprocess, "run", _raise)
    assert latest_tag() == FALLBACK_TAG
    assert "falling back" in capsys.readouterr().err


def test_latest_tag_falls_back_on_nonzero_exit(monkeypatch):
    def _raise(*args, **kwargs):
        raise subprocess.CalledProcessError(128, args)

    monkeypatch.setattr(subprocess, "run", _raise)
    assert latest_tag() == FALLBACK_TAG


def test_fallback_tag_is_itself_a_valid_semver_tag():
    # Guards against FALLBACK_TAG bit-rotting into a non-parseable string.
    major, minor, patch = FALLBACK_TAG.lstrip("v").split(".")
    assert major.isdigit() and minor.isdigit() and patch.isdigit()
