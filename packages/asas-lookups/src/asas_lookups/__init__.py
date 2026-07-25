"""Asas lookups — generic bilingual reference-data engine.

Extraction of Teamy's ``app/lookups`` package (pilot of DR 0017, epic TEAMY-466).
Public surface follows the Asas host contract:

- ``build_routers(get_session)`` — read + admin ``APIRouter``s (host applies auth guards)
- ``configure_org_resolver(fn)`` — optional multi-tenancy hook (default: single-tenant)
- ``seed(session)`` — idempotent reference-data seeding
- ``migrate(engine)`` — package-owned Alembic chain, adopt-or-create
- service functions taking an explicit ``Session``

The implementation lands with the pilot extraction; this skeleton pins the layout and CI.
"""

__version__ = "0.1.0.dev0"
