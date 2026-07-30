"""Action-permission engine (TEAMY-452): org-wide action verbs as config data.

Field permissions answer "may this user change/see this field of this record";
this module answers the *action-level* questions — may they create a team, invite
a user, view the audit log — that previously lived as scattered ``require_role``
guards. A **verb** (``team.create``, ``audit.view``, …) is registered fail-loud by
app-side wiring (mirroring the known-field catalog); grants are ``action_permission``
rows ``(permission, principal)``.

Semantics (mirrors the field engine where it can):

* **Admin floor** — ``admin`` is always allowed, never lockable out via config.
* **Safe-by-default** — a verb with no rows is admin-only. There is no baseline to
  defer to (unlike fields, where the route dependency is the baseline): the verb
  check *is* the gate, so unconfigured means the floor and nothing else.
* **Union-only** — a user holds a verb if any principal they hold is granted it.

Verbs come in two scopes (TEAMY-486). **Org-wide** verbs involve no record:
principals resolve with no relationship resolvers in play (role + groups).
**Record-scoped** verbs (``work_item.edit``, ``project.manage``, …) are checked via
:func:`action_allowed_for` against a concrete record — principals then include the
entity's relationship resolvers and record sources (``project_role:<key>`` families),
so "the lead may", "role holders may", and "the assignee may" are all just grant
rows over one union. Registering a verb as record-scoped makes the org-wide check
fail loud on it — checking such a verb without its record is a programming error.

Framework-agnostic like ``policy.py``: returns booleans, raises nothing HTTP, and
enforcement on/off (``auth_enforce``) is the caller's concern (``auth/deps.py``).
"""

from typing import Any, Optional

from sqlmodel import Session, select

from .models import ActionPermission
from .principals import ROLE_ADMIN, held_principals

# Verbs never resolve against a record, so principals are computed under an entity
# type no relationship resolver registers for — held = global principals only.
_ACTION_SCOPE = "__action__"

_ACTIONS: set[str] = set()
# The subset of _ACTIONS that must be checked against a record (TEAMY-486).
_RECORD_ACTIONS: set[str] = set()

# {permission: {(principal, org_id), ...}} — rebuilt lazily, invalidated on
# write/seed. org_id None = platform default (applies everywhere); an org id
# scopes the grant to that org (WXL-241 slot, activated by the groups admin UI
# TEAMY-454 — an org's grant edits must never leak to other orgs).
_cache: Optional[dict[str, set]] = None


def register_actions(verbs, *, record_scoped: bool = False) -> None:
    """Register (or extend) the catalog of valid action verbs. App-side wiring calls
    this at startup so a typo'd verb in a seed or a check fails loud, mirroring
    ``register_fields`` / ``assert_rules_known``. ``record_scoped=True`` marks the
    verbs as checkable only via :func:`action_allowed_for` (catalog hygiene:
    an org-wide check of a per-record right fails loud)."""
    verbs = set(verbs)
    _ACTIONS.update(verbs)
    if record_scoped:
        _RECORD_ACTIONS.update(verbs)


def known_actions() -> set[str]:
    return set(_ACTIONS)


def record_scoped_actions() -> set[str]:
    """The registered verbs that must be checked against a record."""
    return set(_RECORD_ACTIONS)


def invalidate_action_cache() -> None:
    """Drop the in-memory grant cache (call after seeding/editing rows)."""
    global _cache
    _cache = None


def _grants(session: Session) -> dict[str, set]:
    global _cache
    if _cache is None:
        cache: dict[str, set] = {}
        for row in session.exec(select(ActionPermission)).all():
            cache.setdefault(row.permission, set()).add((row.principal, row.org_id))
        _cache = cache
    return _cache


def granted_principals(
    session: Session, verb: str, org_id: Optional[int] = None
) -> set[str]:
    """The principals explicitly granted ``verb`` (empty when unconfigured):
    platform defaults plus, when ``org_id`` is given, that org's own rows. The
    ``admin`` floor is implicit and NOT included — callers that need the full holder
    set (e.g. the workflow floor resolver) add it themselves."""
    if verb not in _ACTIONS:
        raise ValueError(
            f"unknown action permission {verb!r} — register it via "
            "access.register_actions"
        )
    return {
        p
        for (p, o) in _grants(session).get(verb, set())
        if o is None or (org_id is not None and o == org_id)
    }


def _allowed_principals(session: Session, verb: str, org_id) -> set:
    """The grant allowlist for ``verb`` as seen from ``org_id``: platform defaults
    plus that org's own rows."""
    return {
        p
        for (p, o) in _grants(session).get(verb, set())
        if o is None or o == org_id
    }


def action_allowed(session: Session, user: Any, verb: str) -> bool:
    """May ``user`` perform the org-wide action ``verb``? Admin floor first, then the
    configured allowlist (platform defaults + the caller's own org's rows) against
    the user's held principals. Anonymous holds nothing. Unknown verbs raise — that
    is a programming error, not a policy decision; so is checking a record-scoped
    verb without its record (use :func:`action_allowed_for`)."""
    if verb not in _ACTIONS:
        raise ValueError(
            f"unknown action permission {verb!r} — register it via "
            "access.register_actions"
        )
    if verb in _RECORD_ACTIONS:
        raise ValueError(
            f"action permission {verb!r} is record-scoped — check it via "
            "access.action_allowed_for(session, user, verb, entity_type, record)"
        )
    held = held_principals(user, _ACTION_SCOPE, None, session)
    if ROLE_ADMIN in held:
        return True
    allowed = _allowed_principals(session, verb, getattr(user, "org_id", None))
    return bool(allowed & held)


def action_allowed_for(
    session: Session, user: Any, verb: str, entity_type: str, record: Any
) -> bool:
    """May ``user`` perform ``verb`` on this ``record`` (TEAMY-486)? Same admin
    floor, grant rows, org overrides, and union-only semantics as
    :func:`action_allowed`, but principals resolve **against the record**: the
    entity's relationship resolvers (``project_lead``, ``work_item_assignee``, …)
    and record sources (``project_role:<key>`` families) join the role + group
    set. Works for org-wide verbs too (their grants simply never reference
    record principals). Unknown verbs raise."""
    if verb not in _ACTIONS:
        raise ValueError(
            f"unknown action permission {verb!r} — register it via "
            "access.register_actions"
        )
    held = held_principals(user, entity_type, record, session)
    if ROLE_ADMIN in held:
        return True
    allowed = _allowed_principals(session, verb, getattr(user, "org_id", None))
    return bool(allowed & held)
