# asas-workflow

A graph-based process/approval engine: versioned, code-registered process
definitions (start/approval/system/notify/request-info/end nodes, condition-driven
transitions), instances that pin the exact definition version at open, one
execution row per node activation, quorum approvals (`any`/`all`, negative veto)
with request-info round-trips and delegation, and append-only decisions guarded by
a one-final-verdict partial unique.

Design rules baked in (from Teamy's decision record 0011):

- **The engine decides; owners act.** Completion callbacks apply the effect
  (flip the change set, create the membership); the engine never touches host
  records.
- **Approvals bind to a snapshot** — the subject is frozen at open; edits mean
  cancel + superseding instance.
- **Fail closed, never stall** — an empty assignee resolution falls back to the
  host-registered floor resolver (never silent auto-approve).
- **Events, not live waits** — decisions resume flows via the best-effort
  `events` seam (a notification failure never fails a transition).

Table-owning variant of the Asas host contract (9 tables, member refs are plain
ints — no host FKs):

- **`migrate(engine)`** — package Alembic chain (`alembic_version_asas_workflow`,
  adopt-or-create).
- **`register_definition(spec)` + `seed_workflow_definitions(session)`** —
  code-registered specs, seeded idempotently (validate → hash-compare →
  version-on-change; in-flight instances stay pinned).
- **`registry` hooks** — system handlers, completion callbacks, subject
  renderers, assignee resolvers (incl. `namespace:param` resolvers with
  seed-time param checks), bindable purposes, and the fail-closed floor
  resolver.
- **`events.subscribe(fn)`** — the transactional-outbox bridge for the host's
  notifications.

```python
import asas_workflow as workflow

# boot (host wiring)
workflow.migrate(engine)
workflow.register_assignee_resolver("project_sponsor", resolve_sponsors)
workflow.register_floor_resolver(decision_floor_member_ids)
workflow.register_definition(CHANGE_SET_SPEC)
workflow.register_completion_callback("project_change_set", apply_change_set)
workflow.seed_workflow_definitions(session)

# runtime
instance = workflow.open_instance(session, process_key="project_change_set",
                                  entity_type="project", entity_id=7,
                                  subject_snapshot=diff, initiated_by=member_id)
workflow.decide(session, instance, actor_id=member_id, verdict=workflow.Verdict.positive)
```

See the repo README for the full contract. Extracted from Teamy (workflow epic
WXL-210; extraction epic TEAMY-466 / design record 0017).
