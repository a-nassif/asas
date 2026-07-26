"""Package fixtures. The engine is stateless except for the declared-rules and
known-fields registries — each test declares what it needs; the autouse fixture
resets both so tests never leak into each other."""

import pytest

from asas_validation import catalog, declare_rules


@pytest.fixture(autouse=True)
def _reset_registries():
    yield
    declare_rules(())
    catalog._FIELDS.clear()
