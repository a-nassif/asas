"""A package states its version in three places; all three must agree.

`pyproject.toml` is what pip resolves and what a lockfile records,
`__version__` is what a running process reports, and the newest `CHANGELOG.md`
heading is what a human reads before upgrading. A release that updates two of
the three ships a package that misreports itself — and the misreport is only
visible to whoever hits it.

This is the guard on the per-package tag scheme (see RELEASING.md). Under
lockstep it did not matter much, because the repo tag was the only number anyone
trusted. Now the tag *is* the package version, so these three have to be one
fact rather than three copies of it.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGES = sorted(p for p in (ROOT / "packages").iterdir() if p.is_dir())


def _pyproject_version(pkg: pathlib.Path) -> str:
    text = (pkg / "pyproject.toml").read_text()
    return re.search(r'^version = "([^"]+)"', text, re.M).group(1)


def _dunder_version(pkg: pathlib.Path) -> str:
    init = pkg / "src" / pkg.name.replace("-", "_") / "__init__.py"
    return re.search(r'^__version__ = "([^"]+)"', init.read_text(), re.M).group(1)


def _changelog_version(pkg: pathlib.Path) -> str:
    changelog = pkg / "CHANGELOG.md"
    if not changelog.exists():
        pytest.fail(f"{pkg.name} has no CHANGELOG.md (see RELEASING.md)")
    match = re.search(r"^## (\d+\.\d+\.\d+)", changelog.read_text(), re.M)
    if match is None:
        pytest.fail(f"{pkg.name}/CHANGELOG.md has no '## <version>' heading")
    return match.group(1)


def test_every_package_is_checked():
    """Eleven packages (the original ten plus asas-cli, added deliberately here
    so a twelfth can't slip past this file unnoticed)."""
    assert len(PACKAGES) == 11, [p.name for p in PACKAGES]


@pytest.mark.parametrize("pkg", PACKAGES, ids=lambda p: p.name)
def test_version_agrees_across_all_three(pkg):
    pyproject, dunder, changelog = (
        _pyproject_version(pkg), _dunder_version(pkg), _changelog_version(pkg),
    )
    assert pyproject == dunder == changelog, (
        f"{pkg.name} disagrees with itself: pyproject.toml={pyproject}, "
        f"__version__={dunder}, newest CHANGELOG heading={changelog}. "
        f"A release updates all three (RELEASING.md)."
    )
