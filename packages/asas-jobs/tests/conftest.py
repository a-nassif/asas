"""Standalone package fixtures.

Engine: SQLite temp file by default; Postgres when TEST_DATABASE_URL is set (the CI
matrix runs both). Schema always comes from the package's own migration chain via
``migrate(engine)``, so the chain is exercised on every run. Everything is
function-scoped — each test gets a fresh database.
"""

import os
import tempfile
import uuid

import pytest
from sqlmodel import Session, create_engine

import asas_jobs
from asas_jobs import registry, runner

_TEST_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture()
def engine():
    if _TEST_URL:
        from sqlalchemy import text

        eng = create_engine(_TEST_URL)
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    else:
        path = os.path.join(tempfile.gettempdir(), f"asas_jobs_{uuid.uuid4().hex}.db")
        eng = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
    yield eng
    eng.dispose()
    if not _TEST_URL:
        os.unlink(path)


@pytest.fixture()
def migrated(engine):
    asas_jobs.migrate(engine)
    return engine


@pytest.fixture()
def session(migrated):
    with Session(migrated) as s:
        yield s


@pytest.fixture()
def configured(migrated):
    """Runner wired to this test's engine; registry/binder state reset around the
    test (both are process-global)."""
    asas_jobs.configure_runner(
        lambda: Session(migrated), poll_seconds=0, lease_seconds=60
    )
    yield migrated
    runner._session_factory = None
    registry._HANDLERS.clear()
    registry._context_binder = None
