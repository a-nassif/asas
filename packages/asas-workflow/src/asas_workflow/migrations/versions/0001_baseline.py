"""Baseline: the nine workflow tables at the adopted schema.

The merged final state of Teamy's chain at extraction time (revisions
121f0b6eebc8 engine tables + 5740cca6666e purpose/binding + the org_id columns
from e3b7d92c5a48/b2c9e4f7a180), including the ``uq_node_decision_final``
partial unique (one FINAL verdict per (execution, actor); request_info rows
don't trip it). An adopting host is *stamped* at this revision (see
``migrate.py``); a fresh host runs it.

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

_FINAL = sa.text("verdict IN ('positive', 'negative')")


def _enum(*values, name):
    return sa.Enum(*values, name=name, native_enum=False)


def upgrade() -> None:
    op.create_table(
        "process_definition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("status", _enum("draft", "active", "archived", name="definitionstatus"), nullable=False),
        sa.Column("data_fields", sa.JSON(), nullable=True),
        sa.Column("spec_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", "version", name="uq_process_definition_key_version"),
    )
    with op.batch_alter_table("process_definition", schema=None) as batch_op:
        batch_op.create_index("ix_process_definition_org_id", ["org_id"], unique=False)
        batch_op.create_index("ix_process_definition_key", ["key"], unique=False)
        batch_op.create_index("ix_process_definition_purpose", ["purpose"], unique=False)
        batch_op.create_index("ix_process_definition_status", ["status"], unique=False)

    op.create_table(
        "process_node",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("definition_id", sa.Integer(), nullable=False),
        sa.Column("node_key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", _enum("start", "approval", "system", "notify", "request_info", "end", name="nodetype"), nullable=False),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["definition_id"], ["process_definition.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("definition_id", "node_key", name="uq_process_node_key"),
    )
    with op.batch_alter_table("process_node", schema=None) as batch_op:
        batch_op.create_index("ix_process_node_definition_id", ["definition_id"], unique=False)

    op.create_table(
        "process_transition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("definition_id", sa.Integer(), nullable=False),
        sa.Column("from_node_key", sa.String(), nullable=False),
        sa.Column("to_node_key", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("condition", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["definition_id"], ["process_definition.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("process_transition", schema=None) as batch_op:
        batch_op.create_index("ix_process_transition_definition_id", ["definition_id"], unique=False)

    op.create_table(
        "process_binding",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("definition_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_type", "entity_id", "purpose", name="uq_process_binding"),
    )
    with op.batch_alter_table("process_binding", schema=None) as batch_op:
        batch_op.create_index("ix_process_binding_entity_type", ["entity_type"], unique=False)
        batch_op.create_index("ix_process_binding_entity_id", ["entity_id"], unique=False)

    op.create_table(
        "process_instance",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=True),
        sa.Column("definition_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("subject_snapshot", sa.JSON(), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("status", _enum("running", "completed", "canceled", "error", name="instancestatus"), nullable=False),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("current_node_key", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("initiated_by", sa.Integer(), nullable=True),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["definition_id"], ["process_definition.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["process_instance.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("process_instance", schema=None) as batch_op:
        batch_op.create_index("ix_process_instance_org_id", ["org_id"], unique=False)
        batch_op.create_index("ix_process_instance_definition_id", ["definition_id"], unique=False)
        batch_op.create_index("ix_process_instance_entity_type", ["entity_type"], unique=False)
        batch_op.create_index("ix_process_instance_entity_id", ["entity_id"], unique=False)
        batch_op.create_index("ix_process_instance_status", ["status"], unique=False)
        batch_op.create_index("ix_process_instance_initiated_by", ["initiated_by"], unique=False)

    op.create_table(
        "node_execution",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instance_id", sa.Integer(), nullable=False),
        sa.Column("node_key", sa.String(), nullable=False),
        sa.Column("node_type", _enum("start", "approval", "system", "notify", "request_info", "end", name="nodetype"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("status", _enum("active", "completed", "error", name="executionstatus"), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["instance_id"], ["process_instance.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("node_execution", schema=None) as batch_op:
        batch_op.create_index("ix_node_execution_instance_id", ["instance_id"], unique=False)
        batch_op.create_index("ix_node_execution_status", ["status"], unique=False)

    op.create_table(
        "node_assignee",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_id", sa.Integer(), nullable=False),
        sa.Column("member_id", sa.Integer(), nullable=False),
        sa.Column("via_principal", sa.String(), nullable=False),
        sa.Column("status", _enum("requested", "decided", "not_required", name="assigneestatus"), nullable=False),
        sa.Column("reassigned_from", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["execution_id"], ["node_execution.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("node_assignee", schema=None) as batch_op:
        batch_op.create_index("ix_node_assignee_execution_id", ["execution_id"], unique=False)
        batch_op.create_index("ix_node_assignee_member_id", ["member_id"], unique=False)

    op.create_table(
        "node_decision",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("on_behalf_of", sa.Integer(), nullable=True),
        sa.Column("verdict", _enum("positive", "negative", "request_info", name="verdict"), nullable=False),
        sa.Column("comment", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["node_execution.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("node_decision", schema=None) as batch_op:
        batch_op.create_index("ix_node_decision_execution_id", ["execution_id"], unique=False)
        batch_op.create_index("ix_node_decision_actor_id", ["actor_id"], unique=False)
        batch_op.create_index(
            "uq_node_decision_final",
            ["execution_id", "actor_id"],
            unique=True,
            postgresql_where=_FINAL,
            sqlite_where=_FINAL,
        )

    op.create_table(
        "info_request",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("execution_id", sa.Integer(), nullable=False),
        sa.Column("asked_by", sa.Integer(), nullable=False),
        sa.Column("asked_of", sa.Integer(), nullable=False),
        sa.Column("question", sa.String(), nullable=False),
        sa.Column("answer", sa.String(), nullable=True),
        sa.Column("status", _enum("pending", "answered", "withdrawn", name="inforequeststatus"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["execution_id"], ["node_execution.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("info_request", schema=None) as batch_op:
        batch_op.create_index("ix_info_request_execution_id", ["execution_id"], unique=False)
        batch_op.create_index("ix_info_request_asked_of", ["asked_of"], unique=False)
        batch_op.create_index("ix_info_request_status", ["status"], unique=False)


def downgrade() -> None:
    for table in (
        "info_request",
        "node_decision",
        "node_assignee",
        "node_execution",
        "process_instance",
        "process_binding",
        "process_transition",
        "process_node",
        "process_definition",
    ):
        op.drop_table(table)
