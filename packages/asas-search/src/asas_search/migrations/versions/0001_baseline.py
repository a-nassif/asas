"""Baseline: the ``search_document`` deep-content side table (Postgres only).

The merged final state of Teamy's chain at extraction time (revisions
f3a1c2d4e5b6 table + GIN/entity indexes, b8d4e1f2a3c5 pgvector extension +
embedding columns, f7a2c8d1e934 org_id + org/entity index). **Dialect-branched
by design**: on SQLite this migration records the version and creates nothing —
the deep-content tier is Postgres-only and the engine degrades gracefully.

An adopting Postgres host is *stamped* at this revision (see ``migrate.py``);
a fresh Postgres host runs it. The org_id backfill from f7a2c8d1e934 is not
reproduced: a fresh host has no rows to backfill, and an adopting host was
already backfilled by its own history.

Revision ID: 0001
Revises:
Create Date: 2026-07-28

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE search_document (
            id SERIAL PRIMARY KEY,
            entity_type VARCHAR NOT NULL,
            entity_id INTEGER NOT NULL,
            source VARCHAR NOT NULL,
            source_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            context VARCHAR NOT NULL,
            org_id INTEGER NOT NULL,
            tsv TSVECTOR NOT NULL,
            embedding vector,
            embedding_model VARCHAR,
            CONSTRAINT uq_search_document_source UNIQUE (source, source_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_search_document_tsv ON search_document USING GIN (tsv)")
    op.execute(
        "CREATE INDEX ix_search_document_entity"
        " ON search_document (entity_type, entity_id)"
    )
    op.execute(
        "CREATE INDEX ix_search_document_org_entity"
        " ON search_document (org_id, entity_type)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # The vector extension is left installed: dropping it is a database-wide call.
    op.execute("DROP TABLE search_document")
