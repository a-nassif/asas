"""Seed registered process definitions into the DB (init_db, after wiring).

Thin alias so db.init_db reads like the other seeds; the real logic (validate,
hash-compare, version-on-change) lives in definitions.ensure_definition. V1
production definitions arrive with the flow migrations (WXL-215/216) — until
then this is a no-op unless tests register specs.
"""

from sqlmodel import Session

from .definitions import seed_definitions


def seed_workflow_definitions(session: Session) -> None:
    seed_definitions(session)
