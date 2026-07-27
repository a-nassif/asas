"""Enqueue / claim / settle primitives. Every state transition — claim AND
settle — is a rows-affected CAS update, so correctness never depends on running
a single process: a job reclaimed by another instance after lease expiry cannot
be clobbered by its original (slow) run settling late. Postgres additionally
short-circuits claim contention with ``FOR UPDATE SKIP LOCKED`` on the candidate
select. All functions commit their own transaction."""

from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from .models import BackgroundJob, JobStatus

# Retry backoff: BASE * 2^(attempts-1), capped. attempts is incremented at claim
# time, so the first failure (attempts=1) waits BASE seconds.
BACKOFF_BASE_SECONDS = 30
BACKOFF_CAP_SECONDS = 3600

# States in which a (org, kind, dedupe_key) duplicate or a schedule's previous
# job counts as "still active".
_ACTIVE = (JobStatus.queued, JobStatus.running)


def _active_duplicate(
    session: Session, kind: str, dedupe_key: str, org_id: Optional[int]
) -> Optional[BackgroundJob]:
    """The still-active job holding this idempotency key — scoped per org (the
    tables are tenancy-global, so the query must scope itself; two orgs using
    the same key must never collapse into one job)."""
    return session.exec(
        select(BackgroundJob)
        .where(BackgroundJob.kind == kind)
        .where(BackgroundJob.dedupe_key == dedupe_key)
        .where(BackgroundJob.org_id == org_id)
        .where(BackgroundJob.status.in_(_ACTIVE))
    ).first()


def enqueue(
    session: Session,
    kind: str,
    *,
    payload: Optional[dict] = None,
    org_id: Optional[int] = None,
    run_at: Optional[datetime] = None,
    schedule_id: Optional[int] = None,
    max_attempts: int = 5,
    dedupe_key: Optional[str] = None,
) -> BackgroundJob:
    """Insert a queued job (committed). With ``dedupe_key``, an already-active
    (org, kind, dedupe_key) job is returned instead of stacking a duplicate —
    enforced twice: a fast-path lookup here, and the partial unique indexes on
    active keyed rows for the concurrent-insert race (loser returns the winner)."""
    if max_attempts <= 0:
        raise ValueError(f"job {kind!r}: max_attempts must be positive, got {max_attempts}")
    if dedupe_key is not None:
        existing = _active_duplicate(session, kind, dedupe_key, org_id)
        if existing is not None:
            return existing
    job = BackgroundJob(
        kind=kind,
        payload=payload or {},
        org_id=org_id,
        run_at=run_at or datetime.utcnow(),
        schedule_id=schedule_id,
        max_attempts=max_attempts,
        dedupe_key=dedupe_key,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if dedupe_key is None:
            raise
        existing = _active_duplicate(session, kind, dedupe_key, org_id)
        if existing is None:
            raise
        return existing
    session.refresh(job)
    return job


def claim_next(
    session: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    now: Optional[datetime] = None,
) -> Optional[BackgroundJob]:
    """Claim the oldest due job: status → running, attempts+1, lease set.
    Returns None when nothing is due. The CAS (``WHERE status='queued'``) is the
    correctness guard on both engines; losing it just means another worker won."""
    now = now or datetime.utcnow()
    for _ in range(5):  # a few CAS misses under contention, then give up this tick
        stmt = (
            select(BackgroundJob.id)
            .where(BackgroundJob.status == JobStatus.queued)
            .where(BackgroundJob.run_at <= now)
            .order_by(BackgroundJob.run_at)
            .limit(1)
        )
        if session.get_bind().dialect.name == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        job_id = session.exec(stmt).first()
        if job_id is None:
            session.rollback()  # release the (empty) FOR UPDATE transaction
            return None
        result = session.execute(
            update(BackgroundJob)
            .where(BackgroundJob.id == job_id)
            .where(BackgroundJob.status == JobStatus.queued)
            .values(
                status=JobStatus.running,
                claimed_by=worker_id,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                attempts=BackgroundJob.attempts + 1,
                started_at=now,
            )
        )
        session.commit()
        if result.rowcount == 1:
            return session.get(BackgroundJob, job_id)
    return None


def mark_succeeded(
    session: Session, job: BackgroundJob, *, claimed_by: Optional[str] = None
) -> bool:
    """Settle a finished run — but only if the row is still THIS claim's running
    row (CAS on status + claimant). A job whose lease lapsed mid-run and was
    reclaimed/settled by another instance is left to its new lineage; returns
    False in that case. Pass ``claimed_by`` (the worker id used to claim) — the
    default reads it off the ORM object, which is only safe immediately after
    the claim (a later attribute access refreshes to the *current* claimant)."""
    claimant = claimed_by if claimed_by is not None else job.claimed_by
    result = session.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == job.id)
        .where(BackgroundJob.status == JobStatus.running)
        .where(BackgroundJob.claimed_by == claimant)
        .values(
            status=JobStatus.succeeded,
            finished_at=datetime.utcnow(),
            claimed_by=None,
            lease_expires_at=None,
        )
    )
    session.commit()
    return result.rowcount == 1


def mark_failed(
    session: Session,
    job: BackgroundJob,
    error: str,
    *,
    claimed_by: Optional[str] = None,
    dead: bool = False,
) -> bool:
    """Settle a failed attempt: back to queued with exponential backoff, or
    ``failed`` (the dead-letter state) once attempts are exhausted — ``dead=True``
    dead-letters regardless of attempts left (e.g. no handler registered, where
    retrying can't help), without falsifying the attempt count. Same claimant
    CAS as mark_succeeded; returns False if the row was reclaimed elsewhere."""
    now = datetime.utcnow()
    claimant = claimed_by if claimed_by is not None else job.claimed_by
    if dead or job.attempts >= job.max_attempts:
        values = dict(status=JobStatus.failed, finished_at=now)
    else:
        backoff = min(
            BACKOFF_BASE_SECONDS * 2 ** (job.attempts - 1), BACKOFF_CAP_SECONDS
        )
        values = dict(status=JobStatus.queued, run_at=now + timedelta(seconds=backoff))
    result = session.execute(
        update(BackgroundJob)
        .where(BackgroundJob.id == job.id)
        .where(BackgroundJob.status == JobStatus.running)
        .where(BackgroundJob.claimed_by == claimant)
        .values(
            last_error=error[:2000],
            claimed_by=None,
            lease_expires_at=None,
            **values,
        )
    )
    session.commit()
    return result.rowcount == 1


def reclaim_expired(session: Session, now: Optional[datetime] = None) -> int:
    """Re-queue running jobs whose lease lapsed (killed mid-run by a deploy or
    crash); dead-letter the ones that died on their final allowed attempt.
    Runs at boot and on every tick — a cheap indexed probe first, so the idle
    steady state costs one SELECT, not two no-op UPDATEs + a commit."""
    now = now or datetime.utcnow()
    expired = (
        (BackgroundJob.status == JobStatus.running)
        & (BackgroundJob.lease_expires_at != None)  # noqa: E711 — SQL IS NOT NULL
        & (BackgroundJob.lease_expires_at < now)
    )
    probe = session.exec(select(BackgroundJob.id).where(expired).limit(1)).first()
    if probe is None:
        return 0
    dead = session.execute(
        update(BackgroundJob)
        .where(expired)
        .where(BackgroundJob.attempts >= BackgroundJob.max_attempts)
        .values(
            status=JobStatus.failed,
            finished_at=now,
            claimed_by=None,
            lease_expires_at=None,
            last_error="lease expired on final attempt (worker died mid-run)",
        )
    )
    requeued = session.execute(
        update(BackgroundJob)
        .where(expired)
        .values(
            status=JobStatus.queued,
            run_at=now,
            claimed_by=None,
            lease_expires_at=None,
            last_error="lease expired (worker died mid-run); re-queued",
        )
    )
    session.commit()
    return (dead.rowcount or 0) + (requeued.rowcount or 0)


def has_active(session: Session, schedule_id: int) -> bool:
    """True while a job materialized from this schedule is queued/running — the
    scheduler's no-overlap check."""
    return (
        session.exec(
            select(BackgroundJob.id)
            .where(BackgroundJob.schedule_id == schedule_id)
            .where(BackgroundJob.status.in_(_ACTIVE))
            .limit(1)
        ).first()
        is not None
    )
