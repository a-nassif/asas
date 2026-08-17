"""The migrate(engine) contract: fresh-create, adopt-by-stamp, idempotence."""

import sqlalchemy as sa
from alembic import command

import asas_notifications
from asas_notifications.migrate import _BASELINE, VERSION_TABLE, _config

_TABLES = ("notification", "notification_delivery")


def test_fresh_create(engine):
    asas_notifications.migrate(engine)
    inspector = sa.inspect(engine)
    for t in _TABLES + (VERSION_TABLE,):
        assert inspector.has_table(t), t
    cols = {c["name"] for c in inspector.get_columns("notification_delivery")}
    assert "claimed_at" in cols  # the TEAMY-475 claim column is in the baseline
    cols = {c["name"] for c in inspector.get_columns("notification")}
    assert "archived_at" in cols  # the TEAMY-693 archive axis, added by 0002


def test_idempotent(engine):
    asas_notifications.migrate(engine)
    asas_notifications.migrate(engine)  # second run is a no-op, not an error


def test_adopts_existing_tables(engine):
    """A host whose own historical chain already created the tables (Teamy) must be
    stamped, not re-created: migrate() stamps the baseline and then runs the rest
    of the chain over the adopted tables.

    The adopted schema is built by running the chain *to the baseline* — not from
    today's SQLModel metadata, which drifts ahead of it with every migration the
    chain gains. An adopting host is by definition at the baseline shape.
    """
    command.upgrade(_config(engine), _BASELINE)
    with engine.begin() as conn:
        conn.execute(sa.text(f"DROP TABLE {VERSION_TABLE}"))
    inspector = sa.inspect(engine)
    assert inspector.has_table("notification")
    assert not inspector.has_table(VERSION_TABLE)
    assert "archived_at" not in {c["name"] for c in inspector.get_columns("notification")}

    asas_notifications.migrate(engine)

    inspector = sa.inspect(engine)
    assert inspector.has_table(VERSION_TABLE)
    with engine.connect() as conn:
        version = conn.execute(
            sa.text(f"SELECT version_num FROM {VERSION_TABLE}")  # noqa: S608
        ).scalar()
    assert version is not None
    # Adoption is not just a stamp — the post-baseline chain ran over the
    # adopted tables, so the host lands on the current schema.
    assert "archived_at" in {c["name"] for c in inspector.get_columns("notification")}
