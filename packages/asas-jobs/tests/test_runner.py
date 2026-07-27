"""run_once: handler execution, failure requeue, unknown-kind dead-letter,
context binding, multi-job drain. Ported from Teamy's tests/test_jobs.py
(TEAMY-247) with the extraction (TEAMY-474)."""

from datetime import datetime

from sqlmodel import Session

import asas_jobs as jobs
from asas_jobs.models import BackgroundJob, JobStatus

import uuid


def _kind() -> str:
    """A unique, unregistered kind per call — keeps tests independent."""
    return f"test.{uuid.uuid4().hex[:8]}"


def test_run_once_executes_registered_handler(configured):
    ran_payloads = []
    kind = _kind()
    jobs.register_handler(kind, lambda session, payload: ran_payloads.append(payload))
    with Session(configured) as s:
        job = jobs.enqueue(s, kind, payload={"n": 7})
    jobs.run_once()
    assert ran_payloads == [{"n": 7}]
    with Session(configured) as s:
        job = s.get(BackgroundJob, job.id)
        assert job.status == JobStatus.succeeded
        assert job.finished_at is not None


def test_run_once_failure_requeues_with_error(configured):
    kind = _kind()

    def _boom(session, payload):
        raise RuntimeError("handler exploded")

    jobs.register_handler(kind, _boom)
    with Session(configured) as s:
        job = jobs.enqueue(s, kind)
    jobs.run_once()
    with Session(configured) as s:
        job = s.get(BackgroundJob, job.id)
        assert job.status == JobStatus.queued  # backoff retry, not dead yet
        assert job.run_at > datetime.utcnow()
        assert "handler exploded" in job.last_error


def test_run_once_dead_letters_unknown_kind(configured):
    with Session(configured) as s:
        job = jobs.enqueue(s, _kind())  # never registered
    jobs.run_once()
    with Session(configured) as s:
        job = s.get(BackgroundJob, job.id)
        assert job.status == JobStatus.failed
        assert "no handler registered" in job.last_error
        # dead=True dead-letters without falsifying the true attempt count.
        assert job.attempts == 1


def test_org_job_binds_context_via_configured_binder(configured):
    """The host's binder is called with (session, org_id) before an org-scoped
    handler runs; system jobs (org NULL) skip it."""
    bound = []
    jobs.configure_context_binder(lambda session, org_id: bound.append(org_id))
    seen = []
    kind = _kind()
    jobs.register_handler(kind, lambda session, payload: seen.append(payload))
    with Session(configured) as s:
        jobs.enqueue(s, kind, org_id=42)
        jobs.enqueue(s, kind)  # system job — binder must not fire
    jobs.run_once()
    assert len(seen) == 2
    assert bound == [42]


def test_run_once_drains_multiple_jobs(configured):
    counter = []
    kind = _kind()
    jobs.register_handler(kind, lambda session, payload: counter.append(1))
    with Session(configured) as s:
        for _ in range(5):
            jobs.enqueue(s, kind)
    jobs.run_once()
    assert len(counter) == 5
