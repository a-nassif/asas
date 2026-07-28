"""Package-owned schema migrations — the ``migrate(engine)`` part of the Asas host
contract (DR 0017 §5).

The chain lives in ``migrations/`` inside the package and tracks its position in a
package-scoped version table, so it composes with (never touches) the host's own
Alembic chain. ``migrate`` is **adopt-or-create**:

- fresh host: no version table, no tables → run the chain from the baseline;
- adopting host (e.g. Teamy, whose historical chain already created these tables):
  no version table but the tables exist → *stamp* the baseline, then upgrade.
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import Engine

VERSION_TABLE = "alembic_version_asas_workflow"
_BASELINE = "0001"
_SENTINEL_TABLE = "process_definition"


def _config(engine: Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    cfg.attributes["engine"] = engine
    return cfg


def migrate(engine: Engine) -> None:
    """Bring this package's tables to the current schema. Idempotent; call at boot
    alongside the host's own migrations."""
    inspector = sa.inspect(engine)
    cfg = _config(engine)
    if not inspector.has_table(VERSION_TABLE) and inspector.has_table(_SENTINEL_TABLE):
        command.stamp(cfg, _BASELINE)
    command.upgrade(cfg, "head")
