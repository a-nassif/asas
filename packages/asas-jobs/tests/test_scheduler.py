"""Interval scheduler: tick CAS, catch-up-once, no-overlap, ensure_schedule
idempotence, and the (org, kind) identity uniques. Ported from Teamy's
tests/test_jobs.py (TEAMY-247) with the extraction (TEAMY-474)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

import asas_jobs as jobs
from asas_jobs.models import BackgroundJob, JobSchedule

import uuid


def _kind() -> str:
    """A unique, unregistered kind per call — keeps tests independent."""
    return f"test.{uuid.uuid4().hex[:8]}"


def test_tick_enqueues_once_and_advances_from_now(session):
    now = datetime.utcnow()
    # Overdue by many intervals — downtime catch-up must enqueue ONCE.
    sched = jobs.ensure_schedule(session, _kind(), every_seconds=100)
    sched.next_run_at = now - timedelta(seconds=1000)
    session.add(sched)
    session.commit()
    jobs.tick_schedules(session, now=now)
    session.refresh(sched)
    assert sched.next_run_at == now + timedelta(seconds=100)
    assert sched.last_enqueued_at == now

    def _mine():
        return session.exec(
            select(BackgroundJob).where(BackgroundJob.schedule_id == sched.id)
        ).all()

    assert len(_mine()) == 1
    # Not due again until the interval passes.
    jobs.tick_schedules(session, now=now)
    assert len(_mine()) == 1


def test_tick_no_overlap_skips_but_advances(session):
    now = datetime.utcnow()
    sched = jobs.ensure_schedule(session, _kind(), every_seconds=100)
    sched.next_run_at = now
    session.add(sched)
    session.commit()
    jobs.tick_schedules(session, now=now)  # materializes the first (still-active) run
    later = now + timedelta(seconds=101)
    jobs.tick_schedules(session, now=later)
    session.refresh(sched)
    # The skipped tick still advanced next_run_at — no burst later.
    assert sched.next_run_at == later + timedelta(seconds=100)
    active = session.exec(
        select(BackgroundJob).where(BackgroundJob.schedule_id == sched.id)
    ).all()
    assert len(active) == 1


def test_ensure_schedule_is_idempotent_and_converges(session):
    kind = _kind()
    sched = jobs.ensure_schedule(session, kind, every_seconds=60)
    again = jobs.ensure_schedule(session, kind, every_seconds=90)
    assert again.id == sched.id
    assert again.every_seconds == 90


def test_schedule_identity_unique_index_backstops_seed_race(session):
    """Concurrent boot seeding loses to the (org, kind) partial unique indexes —
    a direct duplicate insert (simulating the racing instance) is rejected, for
    both the system (org NULL) and the org-scoped identity."""
    kind = _kind()
    jobs.ensure_schedule(session, kind, every_seconds=60)  # system (org NULL)
    session.add(JobSchedule(kind=kind, every_seconds=60))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    jobs.ensure_schedule(session, kind, every_seconds=60, org_id=1)
    session.add(JobSchedule(kind=kind, every_seconds=60, org_id=1))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    # A different org (NULL vs set) is a different identity — no conflict.


def test_invalid_cadence_fails_loud(session):
    with pytest.raises(ValueError, match="every_seconds"):
        jobs.ensure_schedule(session, _kind(), every_seconds=0)
