"""notification.archived_at — the inbox's "dealt with" axis.

Separate from ``read_at`` on purpose (Teamy TEAMY-692/693): reading is seeing,
archiving is finishing. A host that shows actionable notifications needs a row to
survive being read and leave only when the recipient acts on it or files it away.

Nullable with no server default — every existing row is un-archived, which is
exactly the intended starting state, so this is a pure add with no backfill.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-18

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notification", schema=None) as batch_op:
        batch_op.drop_column("archived_at")
