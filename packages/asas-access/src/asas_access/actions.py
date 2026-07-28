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

Verbs are org-wide by definition, so no record is involved: principals resolve with
no relationship resolvers in play (their global role today; group names join the
same set with TEAMY-453). Record-scoped rights (``can_manage_team`` etc.) stay
relationship checks — only the role short-circuits inside them route through here.

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

# {permission: {(principal, org_id), ...}} — rebuilt lazily, invalidated on
# write/seed. org_id None = platform default (applies everywhere); an org id
# scopes the grant to that org (WXL-241 slot, activated by the groups admin UI
# TEAMY-454 — an org's grant edits must never leak to other orgs).
_cache: Optional[dict[str, set]] = None


def register_actions(verbs) -> None:
    """Register (or extend) the catalog of valid action verbs. App-side wiring calls
    this at startup so a typo'd verb in a seed or a check fails loud, mirroring
    ``register_fields`` / ``assert_rules_known``."""
    _ACTIONS.update(verbs)


def known_actions() -> set[str]:
    return set(_ACTIONS)


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


def action_allowed(session: Session, user: Any, verb: str) -> bool:
    """May ``user`` perform the org-wide action ``verb``? Admin floor first, then the
    configured allowlist (platform defaults + the caller's own org's rows) against
    the user's held principals. Anonymous holds nothing. Unknown verbs raise — that
    is a programming error, not a policy decision."""
    if verb not in _ACTIONS:
        raise ValueError(
            f"unknown action permission {verb!r} — register it via "
            "access.register_actions"
        )
    held = held_principals(user, _ACTION_SCOPE, None, session)
    if ROLE_ADMIN in held:
        return True
    org_id = getattr(user, "org_id", None)
    allowed = {
        p
        for (p, o) in _grants(session).get(verb, set())
        if o is None or o == org_id
    }
    return bool(allowed & held)
