"""Resolve which Asas repo tag `asas add`/`asas new` pin generated
dependency strings to, when the caller doesn't pass --tag explicitly."""

from __future__ import annotations

import re
import subprocess
import sys

from .registry import REPO_URL

_TAG_RE = re.compile(r"refs/tags/(v\d+\.\d+\.\d+)$")

# Bumped on release. Used only as a last resort — offline, no git on PATH, or
# the remote is unreachable — so `asas add`/`asas new` still work without a
# network, just possibly pinned to a tag that's no longer the newest. Passing
# --tag always wins over both this and live discovery.
FALLBACK_TAG = "v0.15.0"


def _semver_key(tag: str) -> tuple[int, int, int]:
    major, minor, patch = tag.lstrip("v").split(".")
    return (int(major), int(minor), int(patch))


def latest_tag(repo_url: str = REPO_URL, *, timeout: float = 5.0) -> str:
    """The highest ``vX.Y.Z`` tag on the remote, via ``git ls-remote --tags``
    — no local clone needed. Falls back to FALLBACK_TAG (warning on stderr)
    if git is missing, there's no network, or the remote has no such tags."""
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--tags", repo_url],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except Exception as exc:  # noqa: BLE001 — any failure here is a soft fallback
        print(
            f"asas: could not reach {repo_url} to find the latest tag ({exc}); "
            f"falling back to {FALLBACK_TAG}. Pass --tag to pin explicitly.",
            file=sys.stderr,
        )
        return FALLBACK_TAG

    tags: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        ref = parts[1]
        if ref.endswith("^{}"):  # peeled annotated-tag ref — same tag name
            ref = ref[:-3]
        match = _TAG_RE.search(ref)
        if match:
            tags.add(match.group(1))

    if not tags:
        print(
            f"asas: no vX.Y.Z tags found on {repo_url}; falling back to "
            f"{FALLBACK_TAG}. Pass --tag to pin explicitly.",
            file=sys.stderr,
        )
        return FALLBACK_TAG

    return max(tags, key=_semver_key)
