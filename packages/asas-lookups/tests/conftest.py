"""Standalone package fixtures.

Engine: SQLite temp file by default; Postgres when TEST_DATABASE_URL is set (the CI
matrix runs both). Schema always comes from the package's own migration chain via
``migrate(engine)``, so the chain is exercised on every run. Everything is
function-scoped — each test gets a fresh database.
"""

import os
import tempfile
import uuid
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, create_engine

import asas_lookups
from asas_lookups import service

_TEST_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture()
def engine():
    if _TEST_URL:
        eng = create_engine(_TEST_URL)
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    else:
        path = os.path.join(tempfile.gettempdir(), f"asas_lookups_{uuid.uuid4().hex}.db")
        eng = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
    yield eng
    eng.dispose()
    if not _TEST_URL:
        os.unlink(path)


@pytest.fixture()
def migrated(engine):
    asas_lookups.migrate(engine)
    return engine


@pytest.fixture()
def session(migrated):
    with Session(migrated) as s:
        yield s


@pytest.fixture()
def seeded(migrated):
    with Session(migrated) as s:
        asas_lookups.seed(s)
    return migrated


class OrgHolder:
    """Settable stand-in for a host's tenancy context: the resolver reads whatever
    org the test pinned. ``None`` = unscoped (platform/global)."""

    def __init__(self):
        self.org_id: Optional[int] = None


@pytest.fixture()
def org():
    holder = OrgHolder()
    service.configure_org_resolver(lambda session: holder.org_id)
    yield holder
    service.configure_org_resolver(None)


@pytest.fixture()
def client(seeded):
    app = FastAPI()

    def get_session():
        with Session(seeded) as s:
            yield s

    routers = asas_lookups.build_routers(get_session)
    app.include_router(routers.read)
    app.include_router(routers.admin)
    return TestClient(app)
