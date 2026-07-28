"""Baseline: the four access tables at the adopted schema.

The merged final state of Teamy's chain at extraction time (revisions
3bd8349ef15f field_permission + a7d31c90b452 action_permission +
b2c9e4f7a180 org_id override slots + d8b2c4f7a913 org-scoped uniques +
c3f8a91d2e64 group tables). An adopting host is *stamped* at this revision
(see ``migrate.py``); a fresh host runs it.

Revision ID: 0001
Revises:
Create Date: 2026-07-28

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
        "field_permission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("field", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("principal", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_type", "field", "action", "principal", "org_id",
            name="uq_field_permission",
        ),
    )
    with op.batch_alter_table("field_permission", schema=None) as batch_op:
        batch_op.create_index("ix_field_permission_entity_type", ["entity_type"], unique=False)
        batch_op.create_index("ix_field_permission_org_id", ["org_id"], unique=False)

    op.create_table(
        "action_permission",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("permission", sa.String(), nullable=False),
        sa.Column("principal", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "permission", "principal", "org_id", name="uq_action_permission"
        ),
    )
    with op.batch_alter_table("action_permission", schema=None) as batch_op:
        batch_op.create_index("ix_action_permission_org_id", ["org_id"], unique=False)
        batch_op.create_index("ix_action_permission_permission", ["permission"], unique=False)

    op.create_table(
        "access_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "key", name="uq_access_group_org_key"),
    )
    with op.batch_alter_table("access_group", schema=None) as batch_op:
        batch_op.create_index("ix_access_group_org_id", ["org_id"], unique=False)
        batch_op.create_index("ix_access_group_key", ["key"], unique=False)

    op.create_table(
        "access_group_membership",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("org_membership_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["access_group.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "group_id", "org_membership_id", name="uq_access_group_membership"
        ),
    )
    with op.batch_alter_table("access_group_membership", schema=None) as batch_op:
        batch_op.create_index(
            "ix_access_group_membership_group_id", ["group_id"], unique=False
        )
        batch_op.create_index(
            "ix_access_group_membership_org_membership_id",
            ["org_membership_id"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("access_group_membership")
    op.drop_table("access_group")
    op.drop_table("action_permission")
    op.drop_table("field_permission")
