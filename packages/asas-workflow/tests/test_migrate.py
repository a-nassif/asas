"""The migrate(engine) contract: fresh-create, adopt-by-stamp, idempotence."""

import pytest
import sqlalchemy as sa
from sqlmodel import SQLModel

import asas_workflow
from asas_workflow.migrate import _SENTINEL_COLUMNS, _SENTINEL_TABLE, VERSION_TABLE
from asas_workflow.models import (
    InfoRequest,
    NodeAssignee,
    NodeDecision,
    NodeExecution,
    ProcessBinding,
    ProcessDefinition,
    ProcessInstance,
    ProcessNode,
    ProcessTransition,
)

_TABLES = (
    "process_definition",
    "process_node",
    "process_transition",
    "process_binding",
    "process_instance",
    "node_execution",
    "node_assignee",
    "node_decision",
    "info_request",
)
_WORKFLOW_SQLMODEL_TABLES = [
    ProcessDefinition.__table__,
    ProcessNode.__table__,
    ProcessTransition.__table__,
    ProcessBinding.__table__,
    ProcessInstance.__table__,
    NodeExecution.__table__,
    NodeAssignee.__table__,
    NodeDecision.__table__,
    InfoRequest.__table__,
]


def test_fresh_create(engine):
    asas_workflow.migrate(engine)
    inspector = sa.inspect(engine)
    for t in _TABLES + (VERSION_TABLE,):
        assert inspector.has_table(t), t
    # The one-final-verdict partial unique from the baseline.
    names = {ix["name"] for ix in inspector.get_indexes("node_decision")}
    assert "uq_node_decision_final" in names


def test_idempotent(engine):
    asas_workflow.migrate(engine)
    asas_workflow.migrate(engine)  # second run is a no-op, not an error


def test_adopts_existing_tables(engine):
    """A host whose own historical chain already created the tables (Teamy) must be
    stamped, not re-created: migrate() succeeds and records the version."""
    SQLModel.metadata.create_all(engine, tables=_WORKFLOW_SQLMODEL_TABLES)
    inspector = sa.inspect(engine)
    assert not inspector.has_table(VERSION_TABLE)

    asas_workflow.migrate(engine)

    inspector = sa.inspect(engine)
    assert inspector.has_table(VERSION_TABLE)
    with engine.connect() as conn:
        version = conn.execute(
            sa.text(f"SELECT version_num FROM {VERSION_TABLE}")  # noqa: S608
        ).scalar()
    assert version is not None


def test_rejects_a_foreign_table_of_the_same_name(engine):
    """A host that already owns an unrelated table called ``process_definition`` must get a
    loud error, not a silent adoption.

    Adoption keys on a table *name*, and a name is not an identity. Without this
    guard asas-workflow stamps the baseline as applied, therefore skips it entirely —
    leaving the baseline's sibling tables uncreated — and returns success, only
    to fail much later at runtime with no way to repair by re-running.
    """
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE process_definition ("
                "  id INTEGER PRIMARY KEY, candidate_id INTEGER, headline VARCHAR"
                ")"
            )
        )

    with pytest.raises(RuntimeError) as excinfo:
        asas_workflow.migrate(engine)

    message = str(excinfo.value)
    assert "process_definition" in message
    assert "asas-workflow" in message
    # Nothing was stamped, so a later run against a corrected database still works.
    assert not sa.inspect(engine).has_table(VERSION_TABLE)


def test_rejects_a_partial_baseline_schema(engine):
    """Sentinel present and correctly shaped, a sibling baseline table missing.

    Reported by CodeRabbit on asas#18 and reproduced before fixing: the sentinel
    check alone passed, migrate() stamped the baseline as applied, and
    'info_request' was never created — silently, with the stamp meaning a re-run
    could not repair it. Same failure class as the foreign-table case, one layer
    down.
    """
    with engine.begin() as conn:
        coldefs = ", ".join(
            f"{c} INTEGER" if c == "id" else f"{c} VARCHAR"
            for c in sorted(_SENTINEL_COLUMNS)
        )
        conn.execute(sa.text(f"CREATE TABLE {_SENTINEL_TABLE} ({coldefs})"))

    with pytest.raises(RuntimeError) as excinfo:
        asas_workflow.migrate(engine)

    message = str(excinfo.value)
    assert 'info_request' in message
    assert not sa.inspect(engine).has_table(VERSION_TABLE)
