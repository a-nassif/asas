"""Baseline: background_job + job_schedule at the adopted schema.

The merged final state of Teamy's chain at extraction time (revisions
2ba552403ac1 + c4e8f2a91b57), minus the host-side org FK — ``org_id`` is a plain
indexed int here (the host's org table is its own; adopted Teamy tables keep
their historical FK harmlessly). An adopting host is *stamped* at this revision
(see ``migrate.py``); a fresh host runs it.

Revision ID: 0001
Revises:
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Partial-index predicates (portable SQL — SQLite ≥3.8 and Postgres). NULL
# org_ids never collide in a unique index on either engine, hence the split.
_DEDUPE_ORG = sa.text(
    "status IN ('queued', 'running') AND dedupe_key IS NOT NULL AND org_id IS NOT NULL"
)
_DEDUPE_GLOBAL = sa.text(
    "status IN ('queued', 'running') AND dedupe_key IS NOT NULL AND org_id IS NULL"
)
_SCHED_ORG = sa.text("org_id IS NOT NULL")
_SCHED_GLOBAL = sa.text("org_id IS NULL")


def upgrade() -> None:
    op.create_table(
        "background_job",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "succeeded", "failed", "canceled",
                name="jobstatus", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("claimed_by", sa.String(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("dedupe_key", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("background_job", schema=None) as batch_op:
        batch_op.create_index("ix_background_job_claim", ["status", "run_at"], unique=False)
        batch_op.create_index(
            "ix_background_job_reclaim", ["status", "lease_expires_at"], unique=False
        )
        batch_op.create_index(
            "ix_background_job_schedule_active", ["schedule_id", "status"], unique=False
        )
        batch_op.create_index("ix_background_job_dedupe_key", ["dedupe_key"], unique=False)
        batch_op.create_index("ix_background_job_kind", ["kind"], unique=False)
        batch_op.create_index("ix_background_job_org_id", ["org_id"], unique=False)
        batch_op.create_index("ix_background_job_schedule_id", ["schedule_id"], unique=False)
        batch_op.create_index(
            "ux_background_job_org_dedupe",
            ["org_id", "kind", "dedupe_key"],
            unique=True,
            postgresql_where=_DEDUPE_ORG,
            sqlite_where=_DEDUPE_ORG,
        )
        batch_op.create_index(
            "ux_background_job_global_dedupe",
            ["kind", "dedupe_key"],
            unique=True,
            postgresql_where=_DEDUPE_GLOBAL,
            sqlite_where=_DEDUPE_GLOBAL,
        )

    op.create_table(
        "job_schedule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("every_seconds", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("no_overlap", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(), nullable=False),
        sa.Column("last_enqueued_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("job_schedule", schema=None) as batch_op:
        batch_op.create_index("ix_job_schedule_kind", ["kind"], unique=False)
        batch_op.create_index("ix_job_schedule_next_run_at", ["next_run_at"], unique=False)
        batch_op.create_index("ix_job_schedule_org_id", ["org_id"], unique=False)
        batch_op.create_index(
            "ux_job_schedule_org_kind",
            ["org_id", "kind"],
            unique=True,
            postgresql_where=_SCHED_ORG,
            sqlite_where=_SCHED_ORG,
        )
        batch_op.create_index(
            "ux_job_schedule_global_kind",
            ["kind"],
            unique=True,
            postgresql_where=_SCHED_GLOBAL,
            sqlite_where=_SCHED_GLOBAL,
        )


def downgrade() -> None:
    op.drop_table("job_schedule")
    op.drop_table("background_job")
