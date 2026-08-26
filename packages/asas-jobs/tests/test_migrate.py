"""The migrate(engine) contract: fresh-create, adopt-by-stamp, idempotence."""

import pytest
import sqlalchemy as sa
from sqlmodel import SQLModel

import asas_jobs
from asas_jobs.migrate import _SENTINEL_COLUMNS, _SENTINEL_TABLE, VERSION_TABLE
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


def test_rejects_a_foreign_table_of_the_same_name(engine):
    """A host that already owns an unrelated table called ``background_job`` must get a
    loud error, not a silent adoption.

    Adoption keys on a table *name*, and a name is not an identity. Without this
    guard asas-jobs stamps the baseline as applied, therefore skips it entirely —
    leaving the baseline's sibling tables uncreated — and returns success, only
    to fail much later at runtime with no way to repair by re-running.
    """
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE background_job ("
                "  id INTEGER PRIMARY KEY, candidate_id INTEGER, headline VARCHAR"
                ")"
            )
        )

    with pytest.raises(RuntimeError) as excinfo:
        asas_jobs.migrate(engine)

    message = str(excinfo.value)
    assert "background_job" in message
    assert "asas-jobs" in message
    # Nothing was stamped, so a later run against a corrected database still works.
    assert not sa.inspect(engine).has_table(VERSION_TABLE)


def test_rejects_a_partial_baseline_schema(engine):
    """Sentinel present and correctly shaped, a sibling baseline table missing.

    Reported by CodeRabbit on asas#18 and reproduced before fixing: the sentinel
    check alone passed, migrate() stamped the baseline as applied, and
    'job_schedule' was never created — silently, with the stamp meaning a re-run
    could not repair it. Same failure class as the foreign-table case, one layer
    down.
    """
    with engine.begin() as conn:
        coldefs = ", ".join(
            f"{c} INTEGER" if c == "id" else f"{c} VARCHAR"
            for c in sorted(_SENTINEL_COLUMNS)
        )
        conn.execute(sa.text(f"CREATE TABLE {_SENTINEL_TABLE} ({coldefs})"))

    with pytest.raises(RuntimeError) as excinfo:
        asas_jobs.migrate(engine)

    message = str(excinfo.value)
    assert 'job_schedule' in message
    assert not sa.inspect(engine).has_table(VERSION_TABLE)
