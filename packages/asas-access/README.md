# asas-access

Configuration-driven access control: **field-level view/edit restrictions, org-wide
action verbs, and record visibility are data, not code.** One principal layer feeds
all three engines — a principal is a role tier (`admin`/`member`/`viewer`), a group
key (org-wide functional bundle, membership resolved query-time), or a relationship
resolved per (user, record) (`self`, `supervisor`, `team_lead`, …).

Semantics are safe-by-default and union-only:

- A field with **no** `field_permission` rows keeps the caller's baseline rule; rows
  switch it to an explicit allowlist. Only an *actual* change is rejected.
- A verb with **no** `action_permission` rows is admin-only; rows form the allowlist.
- **`admin` is the implicit floor** — never lockable out via config.
- Groups grant by union; leaving a group is how a permission is taken away.

Table-owning variant of the Asas host contract (no routers, seeds take host data):

- **`migrate(engine)`** — package Alembic chain (`alembic_version_asas_access`,
  adopt-or-create: a host whose own chain already created the tables is stamped).
- **`register_fields` / `register_actions`** — fail-loud catalogs, so a typo'd
  field/verb in config errors at seed/check time.
- **`register_resolver(entity_type, principal, fn)`** — how a relationship principal
  is decided; **`register_global_source(fn)`** — record-independent principals
  (the host's group-membership query lives host-side).
- **`register_record_source(entity_type, fn)`** — record-scoped principal *families*
  (TEAMY-486): `fn(user, record, session) -> set[str]` returns every namespaced
  principal the user holds on that record (e.g. `project_role:<key>` per project
  role), so the possible principals are data, not one registration per code.
- **`register_actions(verbs, record_scoped=True)`** + **`action_allowed_for(session,
  user, verb, entity_type, record)`** — record-scoped verbs: same floor/grants/union
  as `action_allowed`, principals resolved against the record (resolvers + record
  sources included). Checking a record-scoped verb org-wide fails loud.
- **`reserve_principals(extra)`** — extend the reserved group-key namespace with
  host history (e.g. retired role values).
- **`seed_field_permissions(session, defaults)` / `seed_action_permissions(session,
  defaults)` / `ensure_system_groups(session, org_id, groups)`** — idempotent
  mechanisms; the *policy data* is the host's.

```python
import asas_access as access

# boot (host wiring)
access.migrate(engine)
access.register_actions(["team.create", "audit.view"])
access.register_resolver("member", access.SELF, lambda user, rec, s: user.member_id == rec.id)
access.register_global_source(my_group_keys_query)
access.reserve_principals({"hr"})                       # retired host roles
access.seed_action_permissions(session, [("team.create", "people_ops")])

# request paths
access.action_allowed(session, user, "team.create")     # org-wide verb gate
access.action_allowed_for(session, user, "project.manage", "project", project)  # record-scoped
access.forbidden_edits(session, user, "member", record, changes)  # -> 403 fields
access.redact_view(session, user, "member", read_model, record)   # null unviewable
access.can_view_record(session, user, "team", team)     # public/private
```

Enforcement on/off is the caller's concern throughout — the engines return booleans
and never raise HTTP.

See the repo README for the full contract. Extracted from Teamy (access epic
WXL-112, actions TEAMY-452, groups TEAMY-453; extraction epic TEAMY-466 / design
record 0017).
