"""Queue tables. Rows carry a plain ``org_id`` int — **no FK** to any host
table (the host's org table is its own; a multi-tenant host scopes handlers via
the context binder, see ``registry.py``). In a tenancy-scoped host these tables
are classified **global**: rows are claimed by the worker *before* any tenant
context exists — per-org scoping is applied by the runner, which binds the
job's org context onto the handler's session."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, Index, JSON, text
from sqlalchemy import Enum as SAEnum
from sqlmodel import Field, SQLModel

# Partial-index predicates for the dedupe uniqueness guarantee (below). Two
# indexes because NULLs never collide in a unique index on either engine — the
# org-NULL (system) rows need their own.
_DEDUPE_ORG = "status IN ('queued', 'running') AND dedupe_key IS NOT NULL AND org_id IS NOT NULL"
_DEDUPE_GLOBAL = "status IN ('queued', 'running') AND dedupe_key IS NOT NULL AND org_id IS NULL"

# Same NULL-split for the schedule identity: one schedule per (org, kind) —
# backs ensure_schedule's check-then-insert against concurrent boot seeding
# (two instances double-seeding would each tick independently).
_SCHED_ORG = "org_id IS NOT NULL"
_SCHED_GLOBAL = "org_id IS NULL"


class JobStatus(str, Enum):
    """Lifecycle of one execution. ``failed`` (attempts exhausted) is terminal and
    doubles as the dead-letter state — visible, and retryable by re-queueing."""

    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    canceled = "canceled"


class BackgroundJob(SQLModel, table=True):
    """One execution of a registered handler. At-least-once: a claim increments
    ``attempts`` up front, so a crash mid-run costs an attempt when the lease
    reclaim re-queues it — a poison job can never loop forever."""

    __tablename__ = "background_job"
    __table_args__ = (
        # The claim query's exact shape: status = queued AND run_at <= now.
        Index("ix_background_job_claim", "status", "run_at"),
        # reclaim_expired's probe: status = running AND lease_expires_at < now.
        Index("ix_background_job_reclaim", "status", "lease_expires_at"),
        # has_active (the no-overlap check): schedule_id = ? AND status IN (...).
        Index("ix_background_job_schedule_active", "schedule_id", "status"),
        # The dedupe contract's actual guarantee: at most one ACTIVE keyed job
        # per (org, kind, dedupe_key) — enqueue's check-then-insert alone would
        # race under concurrency; the loser gets IntegrityError and returns the
        # winner. Partial indexes work on both engines (SQLite ≥3.8, Postgres).
        Index(
            "ux_background_job_org_dedupe",
            "org_id",
            "kind",
            "dedupe_key",
            unique=True,
            postgresql_where=text(_DEDUPE_ORG),
            sqlite_where=text(_DEDUPE_ORG),
        ),
        Index(
            "ux_background_job_global_dedupe",
            "kind",
            "dedupe_key",
            unique=True,
            postgresql_where=text(_DEDUPE_GLOBAL),
            sqlite_where=text(_DEDUPE_GLOBAL),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # NULL = system/cross-org job; set = the org whose context the runner binds
    # (via the host's configured binder) before invoking the handler.
    org_id: Optional[int] = Field(default=None, index=True)
    kind: str = Field(index=True)  # handler name in the registry
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    # native_enum=False keeps the runtime type a plain VARCHAR, matching the
    # migration (dual-engine rule).
    status: JobStatus = Field(
        default=JobStatus.queued,
        sa_column=Column(SAEnum(JobStatus, native_enum=False), nullable=False),
    )
    # Earliest execution time — "queued" really means "queued and due". Backoff
    # retries and delayed jobs are both just a future run_at.
    run_at: datetime = Field(default_factory=datetime.utcnow)
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=5)
    # Claim lease: holder identity + expiry. A running job whose lease lapsed was
    # killed mid-run (deploy/crash) — reclaim_expired re-queues or dead-letters it.
    claimed_by: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    last_error: Optional[str] = None
    # Set when a schedule tick materialized this job — the no-overlap check keys
    # on it. Plain int (no FK): job history must never block deleting a schedule.
    schedule_id: Optional[int] = Field(default=None, index=True)
    # Optional producer-supplied idempotency key: while a (kind, dedupe_key) job
    # is still active, enqueue returns it instead of stacking a duplicate.
    dedupe_key: Optional[str] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class JobSchedule(SQLModel, table=True):
    """A recurring trigger: every ``every_seconds``, materialize a ``BackgroundJob``
    for ``kind``. Interval-only in v1 (cron + org-local timezones are a follow-up).
    Catch-up policy after downtime: enqueue **once**, then advance ``next_run_at``
    from *now* — never once per missed interval."""

    __tablename__ = "job_schedule"
    __table_args__ = (
        Index(
            "ux_job_schedule_org_kind",
            "org_id",
            "kind",
            unique=True,
            postgresql_where=text(_SCHED_ORG),
            sqlite_where=text(_SCHED_ORG),
        ),
        Index(
            "ux_job_schedule_global_kind",
            "kind",
            unique=True,
            postgresql_where=text(_SCHED_GLOBAL),
            sqlite_where=text(_SCHED_GLOBAL),
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: Optional[int] = Field(default=None, index=True)
    kind: str = Field(index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    every_seconds: int
    enabled: bool = Field(default=True)
    # Skip the tick while this schedule's previous job is still queued/running —
    # e.g. an agent must never double-scan a project. The skipped tick still
    # advances next_run_at (no stacking, no burst after a long job).
    no_overlap: bool = Field(default=True)
    # Defaults to "due now": a freshly seeded schedule fires on the next tick.
    next_run_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_enqueued_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
