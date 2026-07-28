"""Baseline: notification + notification_delivery at the adopted schema.

The merged final state of Teamy's chain at extraction time (revisions
d4f2b8a91c37 core + 7871b5b769c1 claimed_at/`sending` status — TEAMY-475),
minus the host-side org/user FKs — plain indexed ints here (the host's org and
user tables are its own; adopted Teamy tables keep their historical FKs
harmlessly). An adopting host is *stamped* at this revision (see ``migrate.py``);
a fresh host runs it.

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
        "notification",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column(
            "category",
            sa.Enum("action", "info", "warning", name="category", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "urgency",
            sa.Enum("low", "normal", "high", name="urgency", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Enum(
                "requested", "participant", "watching", name="reason", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.String(), nullable=True),
        sa.Column("link", sa.String(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.create_index("ix_notification_org_id", ["org_id"], unique=False)
        batch_op.create_index("ix_notification_user_id", ["user_id"], unique=False)
        batch_op.create_index("ix_notification_kind", ["kind"], unique=False)

    op.create_table(
        "notification_delivery",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("notification_id", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending", "sending", "sent", "failed", "skipped",
                name="deliverystatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["notification_id"], ["notification.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("notification_delivery", schema=None) as batch_op:
        batch_op.create_index(
            "ix_notification_delivery_notification_id", ["notification_id"], unique=False
        )
        batch_op.create_index("ix_notification_delivery_channel", ["channel"], unique=False)
        batch_op.create_index("ix_notification_delivery_status", ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("notification_delivery")
    op.drop_table("notification")
