"""The migrate(engine) contract, including the dialect branch: fresh-create and
adopt-by-stamp on Postgres; a version-only no-op on SQLite."""

import pytest
import sqlalchemy as sa

import asas_search
from asas_search.migrate import VERSION_TABLE

from conftest import requires_postgres


def test_migrate_records_version_on_both_engines(engine):
    asas_search.migrate(engine)
    inspector = sa.inspect(engine)
    assert inspector.has_table(VERSION_TABLE)
    if engine.dialect.name == "postgresql":
        assert inspector.has_table("search_document")
        cols = {c["name"] for c in inspector.get_columns("search_document")}
        assert {"tsv", "embedding", "embedding_model", "org_id"} <= cols
    else:
        assert not inspector.has_table("search_document")  # deep tier is PG-only


def test_idempotent(engine):
    asas_search.migrate(engine)
    asas_search.migrate(engine)  # second run is a no-op, not an error


@requires_postgres
def test_adopts_existing_table(engine):
    """A host whose own historical chain already created search_document (Teamy on
    Postgres) must be stamped, not re-created."""
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(
            sa.text(
                """
                CREATE TABLE search_document (
                    id SERIAL PRIMARY KEY,
                    entity_type VARCHAR NOT NULL, entity_id INTEGER NOT NULL,
                    source VARCHAR NOT NULL, source_id INTEGER NOT NULL,
                    content TEXT NOT NULL, context VARCHAR NOT NULL,
                    org_id INTEGER NOT NULL, tsv TSVECTOR NOT NULL,
                    embedding vector, embedding_model VARCHAR,
                    CONSTRAINT uq_search_document_source UNIQUE (source, source_id)
                )
                """
            )
        )
    asas_search.migrate(engine)
    inspector = sa.inspect(engine)
    assert inspector.has_table(VERSION_TABLE)
    with engine.connect() as conn:
        version = conn.execute(
            sa.text(f"SELECT version_num FROM {VERSION_TABLE}")  # noqa: S608
        ).scalar()
    assert version is not None


def test_rejects_a_foreign_table_of_the_same_name(engine):
    """A host that already owns an unrelated table called ``search_document`` must get a
    loud error, not a silent adoption.

    Adoption keys on a table *name*, and a name is not an identity. Without this
    guard asas-search stamps the baseline as applied, therefore skips it entirely —
    leaving the baseline's sibling tables uncreated — and returns success, only
    to fail much later at runtime with no way to repair by re-running.
    """
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE search_document ("
                "  id INTEGER PRIMARY KEY, candidate_id INTEGER, headline VARCHAR"
                ")"
            )
        )

    with pytest.raises(RuntimeError) as excinfo:
        asas_search.migrate(engine)

    message = str(excinfo.value)
    assert "search_document" in message
    assert "asas-search" in message
    # Nothing was stamped, so a later run against a corrected database still works.
    assert not sa.inspect(engine).has_table(VERSION_TABLE)
