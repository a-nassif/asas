import pytest

from asas_cli.registry import PACKAGES, dependency_string, resolve

EXPECTED_KEYS = {
    "lookups",
    "validation",
    "storage",
    "ratelimit",
    "jobs",
    "access",
    "workflow",
    "notifications",
    "search",
    "mcp",
}


def test_all_ten_packages_registered():
    assert set(PACKAGES) == EXPECTED_KEYS


def test_resolve_by_short_key():
    assert resolve("lookups").dist_name == "asas-lookups"


def test_resolve_by_dist_name():
    assert resolve("asas-lookups").key == "lookups"


def test_resolve_unknown_raises_with_choices():
    with pytest.raises(KeyError, match="unknown Asas package 'nope'"):
        resolve("nope")


def test_dependency_string_shape():
    spec = resolve("ratelimit")
    line = dependency_string(spec, "v0.15.0")
    assert line == (
        "asas-ratelimit @ git+https://github.com/wlootah-a11y/asas.git@v0.15.0"
        "#subdirectory=packages/asas-ratelimit"
    )


def test_every_spec_subdir_matches_its_key():
    for key, spec in PACKAGES.items():
        assert spec.subdir == f"packages/{spec.dist_name}"
        assert spec.import_name == spec.dist_name.replace("-", "_")
