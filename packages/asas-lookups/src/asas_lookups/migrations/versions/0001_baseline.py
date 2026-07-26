"""Baseline: the four lookup tables at extraction time.

Frozen DDL matching the shape Teamy's own chain had built by the TEAMY-466 cutover
(baseline tables + the WXL-241 per-org override pattern: nullable ``org_id`` and the
two partial uniques). Adopting hosts whose tables already exist are *stamped* at this
revision instead of running it — see ``asas_lookups.migrate``.

Dual-engine rule: ``native_enum=False`` (plain VARCHAR), partial indexes declared for
both dialects, no server defaults.

Revision ID: 0001
Revises:
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lookup_type",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("is_hierarchical", sa.Boolean(), nullable=False),
        sa.Column("code_system", sa.String(), nullable=True),
        sa.Column(
            "default_sort",
            sa.Enum("label", "sort_order", name="sortmode", native_enum=False),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lookup_type_key"), "lookup_type", ["key"], unique=True)

    op.create_table(
        "lookup_value",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("type_id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "deprecated", name="lookupstatus", native_enum=False),
            nullable=False,
        ),
        sa.Column("is_default", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("superseded_by_id", sa.Integer(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parent_id"], ["lookup_value.id"]),
        sa.ForeignKeyConstraint(["superseded_by_id"], ["lookup_value.id"]),
        sa.ForeignKeyConstraint(["type_id"], ["lookup_type.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lookup_value_code"), "lookup_value", ["code"], unique=False)
    op.create_index(op.f("ix_lookup_value_type_id"), "lookup_value", ["type_id"], unique=False)
    op.create_index(op.f("ix_lookup_value_org_id"), "lookup_value", ["org_id"], unique=False)
    # Per-org override pattern: NULL org_id = platform seed, an org row shadows it.
    # Two partial uniques because a composite unique treats NULLs as distinct on
    # Postgres (duplicate global codes would slip through).
    op.create_index(
        "uq_value_type_code_global",
        "lookup_value",
        ["type_id", "code"],
        unique=True,
        sqlite_where=sa.text("org_id IS NULL"),
        postgresql_where=sa.text("org_id IS NULL"),
    )
    op.create_index(
        "uq_value_type_code_org",
        "lookup_value",
        ["type_id", "code", "org_id"],
        unique=True,
        sqlite_where=sa.text("org_id IS NOT NULL"),
        postgresql_where=sa.text("org_id IS NOT NULL"),
    )

    op.create_table(
        "lookup_translation",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("value_id", sa.Integer(), nullable=False),
        sa.Column("lang", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("short_label", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["value_id"], ["lookup_value.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("value_id", "lang", name="uq_translation_value_lang"),
    )
    op.create_index(
        op.f("ix_lookup_translation_lang"), "lookup_translation", ["lang"], unique=False
    )
    op.create_index(
        op.f("ix_lookup_translation_value_id"), "lookup_translation", ["value_id"], unique=False
    )

    op.create_table(
        "lookup_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("value_id", sa.Integer(), nullable=False),
        sa.Column("lang", sa.String(), nullable=True),
        sa.Column("alias", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["value_id"], ["lookup_value.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lookup_alias_alias"), "lookup_alias", ["alias"], unique=False)
    op.create_index(op.f("ix_lookup_alias_value_id"), "lookup_alias", ["value_id"], unique=False)


def downgrade() -> None:
    op.drop_table("lookup_alias")
    op.drop_table("lookup_translation")
    op.drop_table("lookup_value")
    op.drop_table("lookup_type")
