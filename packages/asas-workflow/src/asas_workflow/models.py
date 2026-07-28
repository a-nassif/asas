"""Workflow engine tables — definitions (the graph) and instances (one walk each).

Self-contained (house pattern): no imports from app models. Member references are
plain ints without FKs, mirroring changecontrol — the engine is extractable.
Design: docs/src/content/docs/architecture/decisions/0011-workflow-engine.md §3.2–3.3 (WXL-213).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import JSON, Column, Index, UniqueConstraint, text
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel

_CASCADE = {"cascade": "all, delete-orphan"}


# ── enums (stored as plain VARCHAR — native_enum=False in the migration) ──────


class DefinitionStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


class NodeType(str, Enum):
    start = "start"
    approval = "approval"
    system = "system"
    notify = "notify"
    request_info = "request_info"
    end = "end"


class InstanceStatus(str, Enum):
    running = "running"
    completed = "completed"
    canceled = "canceled"
    error = "error"


class ExecutionStatus(str, Enum):
    active = "active"
    completed = "completed"
    error = "error"


class AssigneeStatus(str, Enum):
    requested = "requested"
    decided = "decided"
    not_required = "not_required"  # short-circuited, never deleted (ServiceNow)


class Verdict(str, Enum):
    positive = "positive"  # node may relabel ("Approve"/"Endorse"); storage is canonical
    negative = "negative"
    request_info = "request_info"


class InfoRequestStatus(str, Enum):
    pending = "pending"
    answered = "answered"
    withdrawn = "withdrawn"  # auto, when the execution completes without the answer


FINAL_VERDICTS = (Verdict.positive.value, Verdict.negative.value)


# ── definition side (the graph, versioned; immutable once instanced) ──────────


class ProcessDefinition(SQLModel, table=True):
    __tablename__ = "process_definition"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_process_definition_key_version"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    # Per-org override slot (WXL-241, dormant): NULL = platform default. Resolution
    # activates with the first per-org config consumer; seeds stay global.
    org_id: Optional[int] = Field(default=None, index=True)
    key: str = Field(index=True)  # e.g. "project_change_set"
    version: int = Field(default=1)
    name: str
    entity_type: str  # subject type instances run on ("project", "team", …)
    # What the process is FOR (TEAMY-293) — multiple definitions (variants) may
    # share a purpose; completion callbacks / subject renderers key off it. The
    # DEFAULT definition for a purpose is by convention the one whose key equals
    # the purpose (seeded specs), so exactly one default exists per purpose.
    purpose: str = Field(default="", index=True)
    status: DefinitionStatus = Field(
        default=DefinitionStatus.active,
        sa_column=Column(SAEnum(DefinitionStatus, native_enum=False), nullable=False, index=True),
    )
    # Declared process-data fields (seed values + what system handlers provide);
    # condition fields are validated against this list so a typo fails loud.
    data_fields: list = Field(default_factory=list, sa_column=Column(JSON))
    # Canonical hash of the spec that produced this version; lets the seed loader
    # detect "unchanged" vs "new version" without a structural diff.
    spec_hash: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: Optional[datetime] = None

    nodes: list["ProcessNode"] = Relationship(
        back_populates="definition", sa_relationship_kwargs=_CASCADE
    )
    transitions: list["ProcessTransition"] = Relationship(
        back_populates="definition", sa_relationship_kwargs=_CASCADE
    )


class ProcessNode(SQLModel, table=True):
    __tablename__ = "process_node"
    __table_args__ = (UniqueConstraint("definition_id", "node_key", name="uq_process_node_key"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    definition_id: int = Field(foreign_key="process_definition.id", index=True)
    node_key: str  # stable within the definition
    name: str
    type: NodeType = Field(
        sa_column=Column(SAEnum(NodeType, native_enum=False), nullable=False)
    )
    # Per-type config:
    #   approval:     {principals: [..], quorum: "any"|"all", positive_label,
    #                  negative_label, allow_request_info: bool, due_in_days: int|null}
    #   system:       {handler_key: str}
    #   notify:       {event: str, params: {..}}
    #   request_info: {principal: str, prompt: str}
    #   end:          {outcome: str}
    config: dict = Field(default_factory=dict, sa_column=Column(JSON))

    definition: ProcessDefinition = Relationship(back_populates="nodes")


class ProcessTransition(SQLModel, table=True):
    __tablename__ = "process_transition"

    id: Optional[int] = Field(default=None, primary_key=True)
    definition_id: int = Field(foreign_key="process_definition.id", index=True)
    from_node_key: str
    to_node_key: str
    sort_order: int = Field(default=0)  # evaluation order; first-true wins
    # Structured condition over process data ({"all"/"any": [{field, op, value}]});
    # None = default/else branch (validate_definition requires it to sort last).
    condition: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))

    definition: ProcessDefinition = Relationship(back_populates="transitions")


class ProcessBinding(SQLModel, table=True):
    """A subject's chosen variant for a purpose (TEAMY-293): "project 7 runs its
    change approvals through <definition_key>". No row = the purpose's default.
    Binds the KEY (not a version) — the active version resolves at open, and
    in-flight instances stay pinned as always. Generic over entity types (no FK,
    house decoupling) so teams/orgs can bind later."""

    __tablename__ = "process_binding"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_id", "purpose", name="uq_process_binding"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type: str = Field(index=True)  # "project", …
    entity_id: int = Field(index=True)
    purpose: str
    definition_key: str
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── instance side (one walk of a pinned definition version) ───────────────────


class ProcessInstance(SQLModel, table=True):
    __tablename__ = "process_instance"

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: Optional[int] = Field(default=None, index=True)  # owning org (WXL-237, no FK)
    # Pins the exact definition VERSION — in-flight instances never re-shape.
    definition_id: int = Field(foreign_key="process_definition.id", index=True)
    entity_type: str = Field(index=True)
    entity_id: int = Field(index=True)
    # The payload/diff being approved, frozen at open (GitHub lesson: an approval
    # binds to a version of the thing; edits = cancel + superseding instance).
    subject_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # Process data: seeded at open, enriched by system nodes and info answers,
    # read by transition conditions; node results land under nodes.<node_key>.
    data: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: InstanceStatus = Field(
        default=InstanceStatus.running,
        sa_column=Column(SAEnum(InstanceStatus, native_enum=False), nullable=False, index=True),
    )
    outcome: Optional[str] = None  # from the end node reached (or "rejected" via veto)
    current_node_key: Optional[str] = None
    error: Optional[str] = None
    initiated_by: Optional[int] = Field(default=None, index=True)  # member id, no FK
    supersedes_id: Optional[int] = Field(default=None, foreign_key="process_instance.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    executions: list["NodeExecution"] = Relationship(
        back_populates="instance", sa_relationship_kwargs=_CASCADE
    )


class NodeExecution(SQLModel, table=True):
    """One row PER ACTIVATION of a node — request_info (and future send-back) make
    revisits legal; each run is its own auditable episode."""

    __tablename__ = "node_execution"

    id: Optional[int] = Field(default=None, primary_key=True)
    instance_id: int = Field(foreign_key="process_instance.id", index=True)
    node_key: str
    node_type: NodeType = Field(
        sa_column=Column(SAEnum(NodeType, native_enum=False), nullable=False)
    )
    seq: int = Field(default=1)  # activation counter within the instance
    status: ExecutionStatus = Field(
        default=ExecutionStatus.active,
        sa_column=Column(SAEnum(ExecutionStatus, native_enum=False), nullable=False, index=True),
    )
    result: dict = Field(default_factory=dict, sa_column=Column(JSON))
    error: Optional[str] = None
    activated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    instance: ProcessInstance = Relationship(back_populates="executions")
    assignees: list["NodeAssignee"] = Relationship(
        back_populates="execution", sa_relationship_kwargs=_CASCADE
    )
    decisions: list["NodeDecision"] = Relationship(
        back_populates="execution", sa_relationship_kwargs=_CASCADE
    )
    info_requests: list["InfoRequest"] = Relationship(
        back_populates="execution", sa_relationship_kwargs=_CASCADE
    )


class NodeAssignee(SQLModel, table=True):
    """Resolved people, snapshot at node activation (who WAS asked, via which rule)."""

    __tablename__ = "node_assignee"

    id: Optional[int] = Field(default=None, primary_key=True)
    execution_id: int = Field(foreign_key="node_execution.id", index=True)
    member_id: int = Field(index=True)  # no FK — decoupling
    via_principal: str  # which rule produced them ("project_sponsor", "admin_floor", …)
    status: AssigneeStatus = Field(
        default=AssigneeStatus.requested,
        sa_column=Column(SAEnum(AssigneeStatus, native_enum=False), nullable=False),
    )
    reassigned_from: Optional[int] = None  # member id; admin reassignment audit

    execution: NodeExecution = Relationship(back_populates="assignees")


class NodeDecision(SQLModel, table=True):
    """Append-only; never overwritten. One FINAL verdict per (execution, actor) —
    the partial unique index below lets a request_info precede the actor's final
    approve/reject without tripping the constraint (works on SQLite and Postgres)."""

    __tablename__ = "node_decision"
    __table_args__ = (
        Index(
            "uq_node_decision_final",
            "execution_id",
            "actor_id",
            unique=True,
            sqlite_where=text("verdict IN ('positive', 'negative')"),
            postgresql_where=text("verdict IN ('positive', 'negative')"),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    execution_id: int = Field(foreign_key="node_execution.id", index=True)
    actor_id: int = Field(index=True)  # member id, no FK
    on_behalf_of: Optional[int] = None  # delegation (WXL-217): delegator's member id
    verdict: Verdict = Field(
        sa_column=Column(SAEnum(Verdict, native_enum=False), nullable=False)
    )
    comment: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    execution: NodeExecution = Relationship(back_populates="decisions")


class InfoRequest(SQLModel, table=True):
    __tablename__ = "info_request"

    id: Optional[int] = Field(default=None, primary_key=True)
    execution_id: int = Field(foreign_key="node_execution.id", index=True)
    asked_by: int  # member id
    asked_of: int = Field(index=True)  # ANY member (owner ruling 2026-07-10), no FK
    question: str
    answer: Optional[str] = None
    status: InfoRequestStatus = Field(
        default=InfoRequestStatus.pending,
        sa_column=Column(SAEnum(InfoRequestStatus, native_enum=False), nullable=False, index=True),
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    answered_at: Optional[datetime] = None

    execution: NodeExecution = Relationship(back_populates="info_requests")


def result_data_key(node_key: str) -> str:
    """Dotted path under which a node's result lands in instance.data."""
    return f"nodes.{node_key}"


def merge_result(data: dict, node_key: str, result: dict) -> dict:
    """Return a new data dict with the node result merged under nodes.<node_key>."""
    nodes = dict(data.get("nodes") or {})
    nodes[node_key] = result
    out = dict(data)
    out["nodes"] = nodes
    return out


def get_path(data: dict, path: str) -> Any:
    """Resolve a dotted path into nested dicts; None when any hop is missing."""
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur
