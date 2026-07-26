"""The migrate(engine) contract: fresh-create, adopt-by-stamp, idempotence."""

import sqlalchemy as sa
from sqlmodel import Session, SQLModel

import asas_lookups
from asas_lookups.migrate import VERSION_TABLE
from asas_lookups.models import LookupAlias, LookupTranslation, LookupType, LookupValue

_TABLES = ("lookup_type", "lookup_value", "lookup_translation", "lookup_alias")
_LOOKUP_SQLMODEL_TABLES = [
    LookupType.__table__,
    LookupValue.__table__,
    LookupTranslation.__table__,
    LookupAlias.__table__,
]


def test_fresh_create(engine):
    asas_lookups.migrate(engine)
    inspector = sa.inspect(engine)
    for t in _TABLES + (VERSION_TABLE,):
        assert inspector.has_table(t), t
    # org-override partial uniques from the baseline
    names = {ix["name"] for ix in inspector.get_indexes("lookup_value")}
    assert {"uq_value_type_code_global", "uq_value_type_code_org"} <= names


def test_idempotent(engine):
    asas_lookups.migrate(engine)
    asas_lookups.migrate(engine)  # second run is a no-op, not an error
    with Session(engine) as s:
        asas_lookups.seed(s)
        asas_lookups.seed(s)


def test_adopts_existing_tables(engine):
    """A host whose own historical chain already created the tables (Teamy) must be
    stamped, not re-created: migrate() succeeds and records the version."""
    SQLModel.metadata.create_all(engine, tables=_LOOKUP_SQLMODEL_TABLES)
    inspector = sa.inspect(engine)
    assert not inspector.has_table(VERSION_TABLE)

    asas_lookups.migrate(engine)

    inspector = sa.inspect(engine)
    assert inspector.has_table(VERSION_TABLE)
    with engine.connect() as conn:
        version = conn.execute(
            sa.text(f"SELECT version_num FROM {VERSION_TABLE}")  # noqa: S608
        ).scalar()
    assert version is not None
    # Adopted schema is usable as-is.
    with Session(engine) as s:
        asas_lookups.seed(s)
