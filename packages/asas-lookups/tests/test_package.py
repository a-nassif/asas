"""Scaffold smoke test — proves the package installs and imports on both CI engines."""

import asas_lookups


def test_version():
    assert asas_lookups.__version__
