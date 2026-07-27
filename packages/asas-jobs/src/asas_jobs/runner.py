"""The worker: one synchronous pass (:func:`run_once`) and the in-process asyncio
loop (:func:`run_loop`) the app lifespan runs it on.

The session factory and knobs are injected by ``jobs_wiring`` (the package never
imports the app's engine/config). Handlers are sync and run via a thread from the
loop, so the event loop stays responsive; within one process jobs execute
serially — a concurrency knob is future work, and multiple app instances already
parallelize naturally through the claim CAS."""

import asyncio
import logging
import os
import socket
import threading
from datetime import datetime
from typing import Callable, Optional

from . import queue, registry, scheduler

log = logging.getLogger(__name__)

_session_factory: Optional[Callable] = None
_poll_seconds: float = 5.0
_lease_seconds: int = 600

# Set on shutdown: the drain loop checks it between jobs, so an in-flight pass
# exits promptly at a clean job boundary instead of draining its full budget.
_stop_event = threading.Event()

# Upper bound per pass so one flooded queue can't monopolize a tick forever;
# whatever remains is due immediately on the next poll.
MAX_JOBS_PER_PASS = 50


def configure_runner(
    session_factory: Callable, *, poll_seconds: float, lease_seconds: int
) -> None:
    global _session_factory, _poll_seconds, _lease_seconds
    _session_factory = session_factory
    _poll_seconds = poll_seconds
    _lease_seconds = lease_seconds


def request_stop() -> None:
    """Ask an in-flight pass to stop at the next job boundary (shutdown path)."""
    _stop_event.set()


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def run_once(now: Optional[datetime] = None) -> None:
    """One full pass: reclaim lapsed leases → tick schedules → drain due jobs.
    Synchronous and loop-free — tests drive it directly with a pinned ``now``."""
    assert _session_factory is not None, "jobs runner not configured (jobs_wiring)"
    with _session_factory() as session:
        queue.reclaim_expired(session, now=now)
        scheduler.tick_schedules(session, now=now)
    wid = worker_id()
    ran = 0
    while ran < MAX_JOBS_PER_PASS and not _stop_event.is_set():
        with _session_factory() as session:
            job = queue.claim_next(
                session, worker_id=wid, lease_seconds=_lease_seconds, now=now
            )
            if job is None:
                break
            _execute(session, job, wid)
            ran += 1


def _execute(session, job, claimant: str) -> None:
    """Run one claimed job on its own session. The claim is already committed, so
    a handler crash rolls back only the handler's writes; the settle then runs on
    the clean session. Settles are claimant-CAS'd: if the lease lapsed mid-run
    and another instance reclaimed the job, this lineage's settle is a no-op."""
    handler = registry.get_handler(job.kind)
    if handler is None:
        # Unregistered kind: retrying can't help — dead-letter immediately
        # (without falsifying the attempt count).
        queue.mark_failed(
            session,
            job,
            f"no handler registered for kind {job.kind!r}",
            claimed_by=claimant,
            dead=True,
        )
        return
    try:
        registry.bind_job_context(session, job.org_id)
        handler(session, job.payload or {})
        session.commit()
    except Exception as exc:  # noqa: BLE001 — any handler failure = failed attempt
        log.warning("job %s (%s) attempt %s failed", job.id, job.kind, job.attempts,
                    exc_info=True)
        session.rollback()
        queue.mark_failed(
            session, job, f"{type(exc).__name__}: {exc}", claimed_by=claimant
        )
        return
    if not queue.mark_succeeded(session, job, claimed_by=claimant):
        log.warning(
            "job %s (%s) was reclaimed while running (lease lapsed); "
            "success settle skipped — the reclaimed lineage owns the row",
            job.id,
            job.kind,
        )


async def run_loop() -> None:
    """The lifespan loop: run_once in a worker thread, sleep, repeat. On shutdown
    (task cancellation) the in-flight pass is asked to stop at its next job
    boundary and then awaited, so teardown ordering is explicit — a job killed
    with the whole process is brought back by its lease instead."""
    log.info("background-jobs loop starting (poll every %ss)", _poll_seconds)
    _stop_event.clear()
    loop = asyncio.get_running_loop()
    while True:
        pass_future = loop.run_in_executor(None, run_once)
        try:
            await asyncio.shield(pass_future)
        except asyncio.CancelledError:
            request_stop()
            try:
                await pass_future  # let the pass finish its current job cleanly
            except Exception:  # noqa: BLE001 — shutdown must not mask the cancel
                log.warning("final background-jobs pass failed", exc_info=True)
            raise
        except Exception:  # noqa: BLE001 — the loop must survive any pass failure
            log.warning("background-jobs pass failed", exc_info=True)
        await asyncio.sleep(_poll_seconds)
