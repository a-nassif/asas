"""Standalone package fixtures.

Engine: SQLite temp file by default; Postgres when TEST_DATABASE_URL is set (the
CI matrix runs both). The deep-content tier is Postgres-only — its tests skip on
SQLite, mirroring the dialect branch in the package's own migration chain. The
provider/extractor registries and the semantic provider are process-global —
reset around every test.
"""

import os
import tempfile
import uuid

import pytest
from sqlmodel import Session, create_engine

import asas_search
from asas_search import engine as search_engine
from asas_search import fts, semantic

_TEST_URL = os.environ.get("TEST_DATABASE_URL")

requires_postgres = pytest.mark.skipif(
    not (_TEST_URL or "").startswith("postgresql"),
    reason="deep-content tier is Postgres-only",
)


@pytest.fixture(autouse=True)
def _clean_registries():
    yield
    search_engine._PROVIDERS.clear()
    fts._EXTRACTORS.clear()
    semantic.configure(None)


@pytest.fixture()
def engine():
    if _TEST_URL:
        from sqlalchemy import text

        eng = create_engine(_TEST_URL)
        with eng.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
    else:
        path = os.path.join(tempfile.gettempdir(), f"asas_search_{uuid.uuid4().hex}.db")
        eng = create_engine(
            f"sqlite:///{path}", connect_args={"check_same_thread": False}
        )
    yield eng
    eng.dispose()
    if not _TEST_URL:
        os.unlink(path)


@pytest.fixture()
def migrated(engine):
    asas_search.migrate(engine)
    return engine


@pytest.fixture()
def session(migrated):
    with Session(migrated) as s:
        yield s


class FakeEmbeddings:
    """Deterministic 3-dim vectors: hash-bucketed so equal texts embed equal."""

    model = "fake-3d"

    def embed(self, texts):
        out = []
        for t in texts:
            h = abs(hash(t.strip().lower()))
            out.append([(h % 97) / 97.0, ((h // 97) % 89) / 89.0, ((h // 8633) % 83) / 83.0])
        return out
