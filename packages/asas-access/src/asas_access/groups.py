"""Groups: org-wide functional bundles as the third principal source.

A group's ``key`` is a principal string in the same namespace as roles and
relationship principals — both permission tables grant to it with zero engine
change. Semantics are **union-only** (no deny rows: leaving a group is how a
permission is taken away) and **query-time** (membership is resolved per request
via the host-registered global source — never materialized into tokens, sessions,
or search indexes).

This module owns the key namespace guard; the host owns its *catalog* of seeded
system groups (passed to :func:`ensure_system_groups`) and may extend the
reserved namespace via :func:`reserve_principals` (e.g. for retired role values
whose historical config rows must never be re-bound by a custom group). The
membership *query* lives host-side because it joins the host's membership
tables, which this package must not import.
"""

import re
from typing import Dict, Optional

from sqlmodel import Session, select

from .models import AccessGroup
from .principals import (
    CHANGE_APPROVER,
    PROJECT_LEAD,
    ROLE_ADMIN,
    ROLE_MEMBER,
    ROLE_VIEWER,
    SELF,
    SUPERVISOR,
    TEAM_LEAD,
    TEAM_MEMBER,
)

# Group keys share the principal namespace — a collision would silently grant a
# group every permission the colliding principal holds. Base set = the library's
# role tiers + relationship vocabulary; hosts extend it with their own history
# via reserve_principals (e.g. Teamy reserves the retired "hr"/"lead" roles).
_BASE_RESERVED = frozenset(
    {
        ROLE_ADMIN,
        ROLE_MEMBER,
        ROLE_VIEWER,
        SELF,
        SUPERVISOR,
        TEAM_LEAD,
        TEAM_MEMBER,
        PROJECT_LEAD,
        CHANGE_APPROVER,
    }
)

_host_reserved: set = set()


def reserve_principals(extra) -> None:
    """Extend the reserved principal namespace with host-specific strings
    (idempotent). Retired role values belong here so old config rows can never
    be re-bound by a custom group."""
    _host_reserved.update(extra)


def reserved_principals() -> frozenset:
    """The full reserved namespace: library base + host reservations."""
    return frozenset(_BASE_RESERVED | _host_reserved)


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


def validate_group_key(key: str) -> str:
    """Fail-loud namespace guard for a (new) group key. Returns the key."""
    if not _KEY_RE.match(key or ""):
        raise ValueError(
            f"invalid group key {key!r} — lowercase letters/digits/underscores, "
            "starting with a letter"
        )
    if key in reserved_principals():
        raise ValueError(
            f"group key {key!r} collides with a reserved principal "
            "(roles and relationship principals share the namespace)"
        )
    return key


def group_by_key(session: Session, org_id: int, key: str) -> Optional[AccessGroup]:
    return session.exec(
        select(AccessGroup).where(
            AccessGroup.org_id == org_id, AccessGroup.key == key
        )
    ).first()


def ensure_system_groups(
    session: Session, org_id: int, groups: Dict[str, str]
) -> None:
    """Idempotently create the host's seeded system groups (``key -> display
    name``) for one org. Call for every org at boot and for each newly
    provisioned org."""
    for key, name in groups.items():
        validate_group_key(key)
        if group_by_key(session, org_id, key) is None:
            session.add(
                AccessGroup(org_id=org_id, key=key, name=name, is_system=True)
            )
