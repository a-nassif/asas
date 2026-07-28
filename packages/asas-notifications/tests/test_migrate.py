"""The migrate(engine) contract: fresh-create, adopt-by-stamp, idempotence."""

import sqlalchemy as sa
from sqlmodel import SQLModel

import asas_notifications
from asas_notifications.migrate import VERSION_TABLE
from asas_notifications.models import Notification, NotificationDelivery

_TABLES = ("notification", "notification_delivery")
_NOTIF_SQLMODEL_TABLES = [Notification.__table__, NotificationDelivery.__table__]


def test_fresh_create(engine):
    asas_notifications.migrate(engine)
    inspector = sa.inspect(engine)
    for t in _TABLES + (VERSION_TABLE,):
        assert inspector.has_table(t), t
    cols = {c["name"] for c in inspector.get_columns("notification_delivery")}
    assert "claimed_at" in cols  # the TEAMY-475 claim column is in the baseline


def test_idempotent(engine):
    asas_notifications.migrate(engine)
    asas_notifications.migrate(engine)  # second run is a no-op, not an error


def test_adopts_existing_tables(engine):
    """A host whose own historical chain already created the tables (Teamy) must be
    stamped, not re-created: migrate() succeeds and records the version."""
    SQLModel.metadata.create_all(engine, tables=_NOTIF_SQLMODEL_TABLES)
    inspector = sa.inspect(engine)
    assert not inspector.has_table(VERSION_TABLE)

    asas_notifications.migrate(engine)

    inspector = sa.inspect(engine)
    assert inspector.has_table(VERSION_TABLE)
    with engine.connect() as conn:
        version = conn.execute(
            sa.text(f"SELECT version_num FROM {VERSION_TABLE}")  # noqa: S608
        ).scalar()
    assert version is not None
