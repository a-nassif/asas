"""The migrate(engine) contract: fresh-create, adopt-by-stamp, idempotence."""

import pytest
import sqlalchemy as sa
from sqlmodel import SQLModel

import asas_access
from asas_access.migrate import VERSION_TABLE
from asas_access.models import (
    AccessGroup,
    AccessGroupMembership,
    ActionPermission,
    FieldPermission,
)

_TABLES = (
    "field_permission",
    "action_permission",
    "access_group",
    "access_group_membership",
    # MAC layer (0002, DR 0021)
    "clearance_level",
    "marking",
    "subject_clearance",
    "subject_marking",
    "record_marking",
)
_ACCESS_SQLMODEL_TABLES = [
    FieldPermission.__table__,
    ActionPermission.__table__,
    AccessGroup.__table__,
    AccessGroupMembership.__table__,
]


def test_fresh_create(engine):
    asas_access.migrate(engine)
    inspector = sa.inspect(engine)
    for t in _TABLES + (VERSION_TABLE,):
        assert inspector.has_table(t), t
    uniques = {u["name"] for u in inspector.get_unique_constraints("field_permission")}
    assert "uq_field_permission" in uniques
    uniques = {u["name"] for u in inspector.get_unique_constraints("access_group")}
    assert "uq_access_group_org_key" in uniques


def test_idempotent(engine):
    asas_access.migrate(engine)
    asas_access.migrate(engine)  # second run is a no-op, not an error


def test_adopts_existing_tables(engine):
    """A host whose own historical chain already created the tables (Teamy) must be
    stamped, not re-created: migrate() succeeds and records the version."""
    SQLModel.metadata.create_all(engine, tables=_ACCESS_SQLMODEL_TABLES)
    inspector = sa.inspect(engine)
    assert not inspector.has_table(VERSION_TABLE)

    asas_access.migrate(engine)

    inspector = sa.inspect(engine)
    assert inspector.has_table(VERSION_TABLE)
    with engine.connect() as conn:
        version = conn.execute(
            sa.text(f"SELECT version_num FROM {VERSION_TABLE}")  # noqa: S608
        ).scalar()
    assert version is not None


def test_rejects_a_foreign_table_of_the_same_name(engine):
    """A host that already owns an unrelated table called ``field_permission`` must get a
    loud error, not a silent adoption.

    Adoption keys on a table *name*, and a name is not an identity. Without this
    guard asas-access stamps the baseline as applied, therefore skips it entirely —
    leaving the baseline's sibling tables uncreated — and returns success, only
    to fail much later at runtime with no way to repair by re-running.
    """
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE field_permission ("
                "  id INTEGER PRIMARY KEY, candidate_id INTEGER, headline VARCHAR"
                ")"
            )
        )

    with pytest.raises(RuntimeError) as excinfo:
        asas_access.migrate(engine)

    message = str(excinfo.value)
    assert "field_permission" in message
    assert "asas-access" in message
    # Nothing was stamped, so a later run against a corrected database still works.
    assert not sa.inspect(engine).has_table(VERSION_TABLE)
