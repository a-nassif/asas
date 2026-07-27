"""The interval scheduler: materialize due ``JobSchedule`` rows into
``BackgroundJob`` rows. One tick is one pass; the runner calls it every poll."""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from . import queue
from .models import BackgroundJob, JobSchedule

log = logging.getLogger(__name__)


def tick_schedules(session: Session, now: Optional[datetime] = None) -> int:
    """Enqueue a job for every enabled, due schedule; returns how many were
    enqueued. Multi-instance safe: each due row is tick-claimed with a CAS on
    ``next_run_at`` compared against a **plain-value snapshot** taken before any
    commit (ORM attributes would refresh to the current DB value after a commit
    expires them, silently turning the CAS into a tautology). The advance, the
    job insert, and the ``last_enqueued_at`` stamp commit **atomically**, so a
    crash can never advance a schedule without materializing its job. Catch-up-
    once: the new ``next_run_at`` advances from *now*, so downtime never
    produces a burst."""
    now = now or datetime.utcnow()
    # Plain column tuples, not ORM instances: values are snapshotted here and
    # can't be invalidated by the per-schedule commits below.
    due = session.exec(
        select(
            JobSchedule.id,
            JobSchedule.next_run_at,
            JobSchedule.every_seconds,
            JobSchedule.no_overlap,
            JobSchedule.kind,
            JobSchedule.payload,
            JobSchedule.org_id,
        )
        .where(JobSchedule.enabled == True)  # noqa: E712 — SQL boolean comparison
        .where(JobSchedule.next_run_at <= now)
    ).all()
    enqueued = 0
    for sched in due:
        claimed = session.execute(
            update(JobSchedule)
            .where(JobSchedule.id == sched.id)
            .where(JobSchedule.next_run_at == sched.next_run_at)
            .values(next_run_at=now + timedelta(seconds=sched.every_seconds))
        )
        if claimed.rowcount != 1:
            session.rollback()  # another instance won this tick
            continue
        if sched.no_overlap and queue.has_active(session, sched.id):
            # Previous run still going: skip, but commit the advance — no
            # stacking, no burst when the long run finally finishes.
            session.commit()
            continue
        session.add(
            BackgroundJob(
                kind=sched.kind,
                payload=sched.payload or {},
                org_id=sched.org_id,
                schedule_id=sched.id,
                run_at=now,
            )
        )
        session.execute(
            update(JobSchedule)
            .where(JobSchedule.id == sched.id)
            .values(last_enqueued_at=now)
        )
        session.commit()  # advance + job + stamp land together
        enqueued += 1
    return enqueued


def ensure_schedule(
    session: Session,
    kind: str,
    *,
    every_seconds: int,
    payload: Optional[dict] = None,
    org_id: Optional[int] = None,
    no_overlap: bool = True,
) -> JobSchedule:
    """Idempotent seed for code-owned system schedules (called from init_db):
    create the (kind, org_id) schedule if missing, else converge its cadence to
    the code-declared value. ``next_run_at`` is never touched on update, and an
    operator-disabled row (``enabled=False``) is deliberately left disabled —
    but loudly, so a forgotten opt-out doesn't stay silent across deploys.
    Concurrent seeding (two instances booting) is backstopped by the partial
    unique indexes on (org, kind) — the loser re-fetches the winner's row."""
    if every_seconds <= 0:
        raise ValueError(
            f"schedule {kind!r}: every_seconds must be positive, got {every_seconds}"
        )

    def _existing() -> Optional[JobSchedule]:
        return session.exec(
            select(JobSchedule)
            .where(JobSchedule.kind == kind)
            .where(JobSchedule.org_id == org_id)
        ).first()

    sched = _existing()
    if sched is None:
        sched = JobSchedule(
            kind=kind,
            every_seconds=every_seconds,
            payload=payload or {},
            org_id=org_id,
            no_overlap=no_overlap,
        )
        session.add(sched)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()  # presumably another instance seeded it first
            sched = _existing()
            if sched is None:
                # Not the seed race after all (e.g. a bad org FK) — surface it.
                raise
        else:
            session.refresh(sched)
            return sched
    if not sched.enabled:
        log.warning(
            "job schedule %r (org %s) is disabled — leaving it off (operator "
            "opt-out); re-enable via the job_schedule row to resume",
            kind,
            org_id,
        )
    if sched.every_seconds != every_seconds or sched.no_overlap != no_overlap:
        sched.every_seconds = every_seconds
        sched.no_overlap = no_overlap
        session.add(sched)
        session.commit()
    return sched
