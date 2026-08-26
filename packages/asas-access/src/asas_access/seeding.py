"""Idempotent seeding of field-permission and action-permission grant rows.

The *mechanism* lives here; the *policy data* — which grants a deployment ships
with — is the host's (Teamy keeps its defaults in ``app/access_policy.py``),
passed in as plain tuples. Run after ``migrate(engine)`` and after the host has
registered its known fields/verbs; safe to call repeatedly (rows are matched on
their unique key)."""

from typing import Iterable, Tuple

from sqlmodel import Session, select

from . import actions, catalog
from .models import ActionPermission, FieldPermission
from .policy import invalidate_cache

FieldDefault = Tuple[str, str, str, str]  # (entity_type, field, action, principal)
ActionDefault = Tuple[str, str]  # (permission, principal)


def seed_field_permissions(
    session: Session, defaults: Iterable[FieldDefault]
) -> None:
    added = 0
    for entity_type, field, action, principal in defaults:
        if not catalog.is_known(entity_type, field):
            raise ValueError(
                f"field_permission seed references unknown field "
                f"{entity_type}.{field} — register it via register_fields"
            )
        exists = session.exec(
            select(FieldPermission).where(
                FieldPermission.entity_type == entity_type,
                FieldPermission.field == field,
                FieldPermission.action == action,
                FieldPermission.principal == principal,
                # Only a *platform* row satisfies the check — an org-scoped
                # override must not block the global default for other orgs.
                FieldPermission.org_id.is_(None),
            )
        ).first()
        if exists:
            continue
        session.add(
            FieldPermission(
                entity_type=entity_type, field=field, action=action, principal=principal
            )
        )
        added += 1
    if added:
        session.commit()
        invalidate_cache()


def seed_action_permissions(
    session: Session, defaults: Iterable[ActionDefault]
) -> None:
    added = 0
    for permission, principal in defaults:
        if permission not in actions.known_actions():
            raise ValueError(
                f"action_permission seed references unknown verb {permission!r} — "
                "register it via register_actions"
            )
        exists = session.exec(
            select(ActionPermission).where(
                ActionPermission.permission == permission,
                ActionPermission.principal == principal,
                # Only a *platform* row satisfies the check — an org-scoped
                # override must not block the global default for other orgs.
                ActionPermission.org_id.is_(None),
            )
        ).first()
        if exists:
            continue
        session.add(ActionPermission(permission=permission, principal=principal))
        added += 1
    if added:
        session.commit()
        actions.invalidate_action_cache()
