"""Queue primitives with pinned clocks. Ported from Teamy's tests/test_jobs.py
(TEAMY-247) with the extraction (TEAMY-474); org ids are plain ints here (no
host org table)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

import asas_jobs as jobs
from asas_jobs.models import BackgroundJob, JobStatus

import uuid


def _kind() -> str:
    """A unique, unregistered kind per call — keeps tests independent."""
    return f"test.{uuid.uuid4().hex[:8]}"

_CLAIM = dict(worker_id="test-worker", lease_seconds=60)


def test_enqueue_and_claim(session):
    kind = _kind()
    job = jobs.enqueue(session, kind, payload={"x": 1})
    assert job.status == JobStatus.queued
    claimed = jobs.claim_next(session, **_CLAIM)
    assert claimed is not None and claimed.id == job.id
    assert claimed.status == JobStatus.running
    assert claimed.attempts == 1
    assert claimed.claimed_by == "test-worker"
    assert claimed.lease_expires_at is not None
    # Nothing else due — the claim CAS moved the only job out of queued.
    assert jobs.claim_next(session, **_CLAIM) is None


def test_future_run_at_is_not_due(session):
    now = datetime.utcnow()
    jobs.enqueue(session, _kind(), run_at=now + timedelta(hours=1))
    assert jobs.claim_next(session, now=now, **_CLAIM) is None


def test_retry_backoff_then_dead_letter(session):
    now = datetime.utcnow()
    job = jobs.enqueue(session, _kind(), max_attempts=2, run_at=now)
    # Attempt 1 fails → re-queued with backoff.
    claimed = jobs.claim_next(session, now=now, **_CLAIM)
    jobs.mark_failed(session, claimed, "boom")
    session.refresh(claimed)
    assert claimed.status == JobStatus.queued
    assert claimed.run_at > now
    assert claimed.claimed_by is None
    assert "boom" in claimed.last_error
    # Attempt 2 (after the backoff window) fails → dead-letter.
    later = claimed.run_at + timedelta(seconds=1)
    claimed = jobs.claim_next(session, now=later, **_CLAIM)
    assert claimed is not None and claimed.id == job.id
    assert claimed.attempts == 2
    jobs.mark_failed(session, claimed, "boom again")
    session.refresh(claimed)
    assert claimed.status == JobStatus.failed
    assert claimed.finished_at is not None


def test_reclaim_expired_requeues_and_dead_letters(session):
    now = datetime.utcnow()
    # Lease lapsed with attempts left → back to queued.
    retryable = jobs.enqueue(session, _kind(), max_attempts=3, run_at=now)
    jobs.claim_next(session, now=now, worker_id="w", lease_seconds=60)
    # Lease lapsed on the final allowed attempt → dead-letter.
    final = jobs.enqueue(session, _kind(), max_attempts=1, run_at=now)
    jobs.claim_next(session, now=now, worker_id="w", lease_seconds=60)
    reclaimed = jobs.reclaim_expired(session, now=now + timedelta(seconds=61))
    assert reclaimed == 2
    session.expire_all()
    retryable = session.get(BackgroundJob, retryable.id)
    final = session.get(BackgroundJob, final.id)
    assert retryable.status == JobStatus.queued
    assert retryable.claimed_by is None and retryable.lease_expires_at is None
    assert final.status == JobStatus.failed
    # An unexpired lease is left alone.
    assert jobs.reclaim_expired(session, now=now + timedelta(seconds=61)) == 0


def test_dedupe_key_collapses_active_duplicates(session):
    kind = _kind()
    first = jobs.enqueue(session, kind, dedupe_key="k1")
    assert jobs.enqueue(session, kind, dedupe_key="k1").id == first.id
    # A settled job no longer blocks a fresh enqueue.
    claimed = jobs.claim_next(session, **_CLAIM)
    jobs.mark_succeeded(session, claimed)
    assert jobs.enqueue(session, kind, dedupe_key="k1").id != first.id


def test_dedupe_key_is_org_scoped(session):
    """Two orgs using the same (kind, dedupe_key) must never collapse into one
    job — the tables are tenancy-global, so the dedupe query scopes itself."""
    kind = _kind()
    system_job = jobs.enqueue(session, kind, dedupe_key="k")  # org NULL
    org_job = jobs.enqueue(session, kind, dedupe_key="k", org_id=1)
    assert org_job.id != system_job.id
    other_org = jobs.enqueue(session, kind, dedupe_key="k", org_id=2)
    assert other_org.id not in (system_job.id, org_job.id)
    # Within one org (and within the system scope) the key still collapses.
    assert jobs.enqueue(session, kind, dedupe_key="k", org_id=1).id == org_job.id
    assert jobs.enqueue(session, kind, dedupe_key="k").id == system_job.id


def test_dedupe_unique_index_backstops_the_race(session):
    """The check-then-insert race loses to the partial unique index: a direct
    duplicate insert (simulating the concurrent loser) is rejected by the DB."""
    kind = _kind()
    jobs.enqueue(session, kind, dedupe_key="race")
    session.add(BackgroundJob(kind=kind, dedupe_key="race"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_settle_is_ignored_after_reclaim(session):
    """A job reclaimed while (over)running must not be clobbered when the
    original slow run finally settles — the settle CAS no-ops."""
    now = datetime.utcnow()
    job = jobs.enqueue(session, _kind(), run_at=now)
    claimed = jobs.claim_next(session, now=now, worker_id="w1", lease_seconds=60)
    assert claimed is not None
    # Lease lapses; another instance's tick reclaims the job.
    assert jobs.reclaim_expired(session, now=now + timedelta(seconds=61)) == 1
    # The original (slow) run now tries to settle — must be a no-op.
    assert jobs.mark_succeeded(session, claimed, claimed_by="w1") is False
    assert jobs.mark_failed(session, claimed, "late failure", claimed_by="w1") is False
    session.expire_all()
    assert session.get(BackgroundJob, job.id).status == JobStatus.queued


def test_invalid_attempts_fail_loud(session):
    with pytest.raises(ValueError, match="max_attempts"):
        jobs.enqueue(session, _kind(), max_attempts=0)
