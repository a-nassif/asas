"""The migrate(engine) contract: fresh-create, adopt-by-stamp, idempotence."""

import sqlalchemy as sa
from sqlmodel import SQLModel

import asas_jobs
from asas_jobs.migrate import VERSION_TABLE
from asas_jobs.models import BackgroundJob, JobSchedule

_TABLES = ("background_job", "job_schedule")
_JOBS_SQLMODEL_TABLES = [BackgroundJob.__table__, JobSchedule.__table__]


def test_fresh_create(engine):
    asas_jobs.migrate(engine)
    inspector = sa.inspect(engine)
    for t in _TABLES + (VERSION_TABLE,):
        assert inspector.has_table(t), t
    job_ix = {ix["name"] for ix in inspector.get_indexes("background_job")}
    assert {
        "ix_background_job_claim",
        "ux_background_job_org_dedupe",
        "ux_background_job_global_dedupe",
    } <= job_ix
    sched_ix = {ix["name"] for ix in inspector.get_indexes("job_schedule")}
    assert {"ux_job_schedule_org_kind", "ux_job_schedule_global_kind"} <= sched_ix


def test_idempotent(engine):
    asas_jobs.migrate(engine)
    asas_jobs.migrate(engine)  # second run is a no-op, not an error


def test_adopts_existing_tables(engine):
    """A host whose own historical chain already created the tables (Teamy) must be
    stamped, not re-created: migrate() succeeds and records the version."""
    SQLModel.metadata.create_all(engine, tables=_JOBS_SQLMODEL_TABLES)
    inspector = sa.inspect(engine)
    assert not inspector.has_table(VERSION_TABLE)

    asas_jobs.migrate(engine)

    inspector = sa.inspect(engine)
    assert inspector.has_table(VERSION_TABLE)
    with engine.connect() as conn:
        version = conn.execute(
            sa.text(f"SELECT version_num FROM {VERSION_TABLE}")  # noqa: S608
        ).scalar()
    assert version is not None
