"""The migrate(engine) contract: fresh-create, adopt-by-stamp, idempotence."""

import sqlalchemy as sa
from sqlmodel import SQLModel

import asas_workflow
from asas_workflow.migrate import VERSION_TABLE
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
