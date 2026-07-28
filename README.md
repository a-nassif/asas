# Asas (أساس)

**Asas** ("foundation") is a family of reusable FastAPI/SQLModel libraries extracted from
[Teamy](https://github.com/wlootah-a11y/teamy) — self-contained backend modules any internal
product can install: reference-data lookups, access control, validation, background jobs, and more.

Design record: `docs/src/content/docs/architecture/decisions/0017-asas-libraries.md` in the Teamy
repo (DR 0017, epic TEAMY-466).

## Packages

| Package | Import root | Status |
| --- | --- | --- |
| `asas-lookups` | `asas_lookups` | v0.8.0 — extracted (Teamy DR 0017 pilot) |
| `asas-validation` | `asas_validation` | v0.8.0 — extracted (table-less contract variant) |
| `asas-storage` | `asas_storage` | v0.8.0 — extracted (table-less, router-less variant) |
| `asas-ratelimit` | `asas_ratelimit` | v0.8.0 — extracted (table-less, router-less variant) |
| `asas-jobs` | `asas_jobs` | v0.8.0 — extracted (table-owning: package Alembic chain) |
| `asas-access` | `asas_access` | v0.8.0 — extracted (table-owning: package Alembic chain) |
| `asas-workflow` | `asas_workflow` | v0.8.0 — extracted (table-owning: package Alembic chain) |
| `asas-notifications` | `asas_notifications` | v0.8.0 — extracted (table-owning + router variant) |

Planned, in extraction order: `asas-search`, `asas-mcp`.

## The host contract

Every package exposes the same five-part surface — nothing more:

1. **`build_routers(get_session)`** — factory taking the host's FastAPI session dependency and
   returning the package's `APIRouter`s. Auth is composition-time: the host applies its own
   guards when including them; libraries never learn the host's auth model.
2. **`configure_*` hooks** — optional callables for host concerns (e.g.
   `configure_org_resolver(fn)` for multi-tenancy), defaulting to single-tenant/no-op.
3. **`seed(session)`** — idempotent reference-data seeding, called by the host at boot.
4. **`migrate(engine)`** — applies the package-owned Alembic chain (package-scoped version
   table, adopt-or-create bootstrap), called by the host at boot before its own chain.
5. **Service functions take an explicit `Session`** — no engine, session factory, or settings
   import inside a library.

## Rules

- **No app imports, ever.** Packages depend on FastAPI/SQLModel/Alembic and each other's
  published surface — never on a host application.
- **Dual-engine portability**: every package runs on SQLite and Postgres; migrations use batch
  mode, `native_enum=False`, portable server defaults. CI runs both engines per package.
- **No shared kernel yet**: the contract above is a convention, not a package. An `asas-core`
  appears only when a third package repeats identical code.
- **Lockstep versioning**: one version for the repo, tagged `v0.1.0`, `v0.2.0`, ….

## Consuming

Pin a tag via a git install (no package index):

```
asas-lookups @ git+https://github.com/wlootah-a11y/asas.git@v0.1.0#subdirectory=packages/asas-lookups
```

## Developing

Each package is standalone: `cd packages/<name>`, `pip install -e '.[dev]'`, `pytest -q`.
Set `TEST_DATABASE_URL=postgresql+psycopg2://…` to run a package's suite on Postgres
(unset ⇒ SQLite), mirroring Teamy's convention.
