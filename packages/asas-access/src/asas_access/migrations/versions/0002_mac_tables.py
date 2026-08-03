"""The mandatory-access tables (TEAMY-59, DR 0021): org-scoped clearance-level
and marking catalogs, subject assignments keyed by org_membership_id (no FK —
the host owns the join), and the polymorphic record_marking stamps. The record's
level stamp is a host-owned ``classification_code`` column on the entity itself.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clearance_level",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "code", name="uq_clearance_level_org_code"),
    )
    with op.batch_alter_table("clearance_level", schema=None) as batch_op:
        batch_op.create_index("ix_clearance_level_org_id", ["org_id"], unique=False)
        batch_op.create_index("ix_clearance_level_code", ["code"], unique=False)

    op.create_table(
        "marking",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "code", name="uq_marking_org_code"),
    )
    with op.batch_alter_table("marking", schema=None) as batch_op:
        batch_op.create_index("ix_marking_org_id", ["org_id"], unique=False)
        batch_op.create_index("ix_marking_code", ["code"], unique=False)

    op.create_table(
        "subject_clearance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_membership_id", sa.Integer(), nullable=False),
        sa.Column("level_code", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_membership_id", name="uq_subject_clearance"),
    )
    with op.batch_alter_table("subject_clearance", schema=None) as batch_op:
        batch_op.create_index(
            "ix_subject_clearance_org_membership_id",
            ["org_membership_id"],
            unique=False,
        )

    op.create_table(
        "subject_marking",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_membership_id", sa.Integer(), nullable=False),
        sa.Column("marking_code", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_membership_id", "marking_code", name="uq_subject_marking"
        ),
    )
    with op.batch_alter_table("subject_marking", schema=None) as batch_op:
        batch_op.create_index(
            "ix_subject_marking_org_membership_id",
            ["org_membership_id"],
            unique=False,
        )

    op.create_table(
        "record_marking",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=False),
        sa.Column("marking_code", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id", "entity_type", "record_id", "marking_code",
            name="uq_record_marking",
        ),
    )
    with op.batch_alter_table("record_marking", schema=None) as batch_op:
        batch_op.create_index("ix_record_marking_org_id", ["org_id"], unique=False)
        batch_op.create_index(
            "ix_record_marking_entity_type", ["entity_type"], unique=False
        )
        batch_op.create_index(
            "ix_record_marking_record_id", ["record_id"], unique=False
        )


def downgrade() -> None:
    op.drop_table("record_marking")
    op.drop_table("subject_marking")
    op.drop_table("subject_clearance")
    op.drop_table("marking")
    op.drop_table("clearance_level")
