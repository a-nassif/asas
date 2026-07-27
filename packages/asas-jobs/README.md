# asas-jobs

Durable background jobs + interval scheduler: a DB-backed queue (no broker — works
on SQLite and Postgres alike) with an in-process polling worker. Producers `enqueue`
a `kind` + JSON payload (or seed a `JobSchedule` for recurring work); the runner
claims rows with a dialect-aware CAS (`FOR UPDATE SKIP LOCKED` on Postgres), executes
the registered handler, and retries failures with exponential backoff until
`max_attempts` — `failed` rows are the visible, re-queueable dead-letter queue.

Delivery is **at-least-once: every handler must be idempotent.** Crash recovery is
lease-based (`reclaim_expired` at boot and every tick), settles are claimant-CAS'd
(a reclaimed job can't be clobbered by its original slow run), and schedule ticks are
CAS'd with catch-up-once semantics (downtime never produces a burst). Multi-instance
deployments are safe by construction; a dedicated worker is a config choice, not a
code change.

Table-owning variant of the Asas host contract (no routers, no seed):

- **`migrate(engine)`** — applies the package-owned Alembic chain
  (version table `alembic_version_asas_jobs`, adopt-or-create: a host whose own
  historical chain already created the tables is stamped, not re-created).
- **`configure_runner(session_factory, poll_seconds=…, lease_seconds=…)`** — the
  host injects its session factory and knobs; the library reads no configuration.
- **`configure_context_binder(fn)`** — optional `(session, org_id) -> None` hook: a
  multi-tenant host binds the job's org context onto the handler's session before it
  runs. Rows carry a plain `org_id` int (no FK — the host's org table is its own).
- **`register_handler(kind, fn)`** — handlers are `(session, payload) -> None`.

```python
import asas_jobs as jobs

# boot
jobs.migrate(engine)
jobs.configure_runner(lambda: Session(engine), poll_seconds=5, lease_seconds=600)
jobs.register_handler("emails.dispatch", dispatch_pending)
jobs.ensure_schedule(session, "emails.dispatch", every_seconds=60)

# producers
jobs.enqueue(session, "report.build", payload={"id": 42}, dedupe_key="report-42")

# the worker: asyncio loop in the app lifespan, or drive run_once() directly
await jobs.run_loop()
```

See the repo README for the full contract. Extracted from Teamy (background jobs
TEAMY-247 / design record 0016; extraction epic TEAMY-466 / design record 0017).
