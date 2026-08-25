"""Package-owned schema migrations — the ``migrate(engine)`` part of the Asas host
contract (DR 0017 §5).

The chain lives in ``migrations/`` inside the package and tracks its position in a
package-scoped version table, so it composes with (never touches) the host's own
Alembic chain. ``migrate`` is **adopt-or-create**:

- fresh host: no version table, no tables → run the chain from the baseline;
- adopting host (e.g. Teamy, whose historical chain already created these tables):
  no version table but the tables exist → *stamp* the baseline, then upgrade.

Adoption is guarded: a table name is not an identity, so before stamping we check
that the sentinel actually carries the baseline's columns. A host that happens to
own an unrelated table of the same name gets a loud error here rather than a
silently skipped baseline and a runtime failure later (see _assert_adoptable).
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

VERSION_TABLE = "alembic_version_asas_workflow"
_BASELINE = "0001"
_SENTINEL_TABLE = "process_definition"
# Columns the baseline creates on the sentinel. Baselines are frozen, so this
# set is a constant; see _assert_adoptable.
_SENTINEL_COLUMNS = frozenset({
    "id",
    "org_id",
    "key",
    "version",
    "name",
    "entity_type",
    "purpose",
    "status",
    "data_fields",
    "spec_hash",
    "created_at",
    "published_at",
})


def _config(engine: Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.attributes["engine"] = engine
    return cfg


def _assert_adoptable(inspector) -> None:
    """Guard the adopt path in :func:`migrate`.

    Adoption keys on a table *name*, which is not an identity. A host that
    already owns an unrelated table called ``process_definition`` would otherwise have us
    stamp the baseline as applied and therefore **skip it entirely** — leaving
    the baseline's other tables uncreated — and then fail at runtime, far from
    the cause, with no error at migrate time and no way to repair by re-running.

    So require the baseline's own columns to be present before believing the
    table is ours. Extra columns are fine (a later revision, or the host's own
    additions); missing ones mean this is somebody else's table.
    """
    actual = {c["name"] for c in inspector.get_columns(_SENTINEL_TABLE)}
    missing = _SENTINEL_COLUMNS - actual
    if missing:
        raise RuntimeError(
            f"asas-workflow cannot adopt the existing {_SENTINEL_TABLE!r} table: it is "
            f"missing the baseline columns {sorted(missing)}. This database already "
            f"contains an unrelated table named {_SENTINEL_TABLE!r}, so asas-workflow "
            f"cannot use that name. Rename the existing table and retry."
        )


def migrate(engine: Engine) -> None:
    """Bring this package's tables to the current schema. Idempotent; call at boot
    alongside the host's own migrations."""
    inspector = sa.inspect(engine)
    cfg = _config(engine)
    if not inspector.has_table(VERSION_TABLE) and inspector.has_table(_SENTINEL_TABLE):
        _assert_adoptable(inspector)
        command.stamp(cfg, _BASELINE)
    command.upgrade(cfg, "head")
