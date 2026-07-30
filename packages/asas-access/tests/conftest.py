"""Standalone package fixtures.

Engine: SQLite temp file by default; Postgres when TEST_DATABASE_URL is set (the CI
matrix runs both). Schema always comes from the package's own migration chain via
``migrate(engine)``. The engines keep process-global registries and caches
(catalog, actions, resolvers, private viewers, policy caches, host reservations) —
reset around every test so tests stay independent.
"""

import os
import tempfile
import uuid
from types import SimpleNamespace

import pytest
from sqlmodel import Session, create_engine

import asas_access
from asas_access import actions, catalog, groups, policy, principals, visibility

_TEST_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def _clean_registries():
    yield
    catalog._FIELDS.clear()
    actions._ACTIONS.clear()
    actions._RECORD_ACTIONS.clear()
    actions._cache = None
    policy._cache = None
    principals._RESOLVERS.clear()
    principals._GLOBAL_SOURCES.clear()
    principals._RECORD_SOURCES.clear()
    groups._host_reserved.clear()
    visibility._PRIVATE_VIEWERS.clear()


@pytest.fixture()
def engine():
    if _TEST_URL:
        from sqlalchemy import text

        eng = create_engine(_TEST_URL)
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    else:
        path = os.path.join(tempfile.gettempdir(), f"asas_access_{uuid.uuid4().hex}.db")
        eng = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
    yield eng
    eng.dispose()
    if not _TEST_URL:
        os.unlink(path)


@pytest.fixture()
def migrated(engine):
    asas_access.migrate(engine)
    return engine


@pytest.fixture()
def session(migrated):
    with Session(migrated) as s:
        yield s


def make_user(role="member", *, user_id=1, org_id=1, member_id=None):
    """A duck with the attributes the engines read (role by value; org_id for
    org-scoped grants; member_id for relationship resolvers)."""
    return SimpleNamespace(
        role=role, user_id=user_id, org_id=org_id, member_id=member_id
    )
