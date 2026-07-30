"""Principals and the resolver registry.

A **principal** a user holds w.r.t. a record is either their global role or a
relationship that resolves true for that specific (user, record). Owning app modules
register relationship resolvers here (e.g. the members module registers ``self`` /
``supervisor``); this module never imports them, so ``app.access`` stays decoupled.
"""

from collections.abc import Callable
from typing import Any, Optional

# Global roles — string values match ``models.Role`` (read off ``user.role`` by value,
# so this module needn't import the enum). The functional roles ``hr``/``lead`` were
# retired by TEAMY-453 — their grants live on the seeded People Ops / Leads groups.
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"
ROLE_VIEWER = "viewer"

# Relationship principals (resolved against a specific record).
SELF = "self"
SUPERVISOR = "supervisor"
TEAM_LEAD = "team_lead"
TEAM_MEMBER = "team_member"
PROJECT_LEAD = "project_lead"
CHANGE_APPROVER = "change_approver"  # may approve a project's change sets / gated status updates

# (entity_type, principal) -> fn(user, record, session) -> bool
Resolver = Callable[[Any, Any, Any], bool]
_RESOLVERS: dict[tuple[str, str], Resolver] = {}

# fn(user, session) -> set[str]: principals held regardless of entity/record —
# the third source (group keys, TEAMY-453). Registered app-side (access_wiring)
# because the membership join needs app models this package must not import.
GlobalSource = Callable[[Any, Any], set]
_GLOBAL_SOURCES: list[GlobalSource] = []

# entity_type -> [fn(user, record, session) -> set[str]]: the fourth source
# (TEAMY-486) — namespaced principals held w.r.t. one record, where the *set*
# of possible principals is data, not code (e.g. ``project_role:<key>`` for each
# project role the user holds on the record's project). A boolean resolver
# answers one fixed principal; a record source returns the whole family in one
# host-side query.
RecordSource = Callable[[Any, Any, Any], set]
_RECORD_SOURCES: dict[str, list[RecordSource]] = {}


def register_resolver(entity_type: str, principal: str, fn: Resolver) -> None:
    """Register how a relationship ``principal`` is decided for ``entity_type``."""
    _RESOLVERS[(entity_type, principal)] = fn


def register_global_source(fn: GlobalSource) -> None:
    """Register a source of record-independent principals (e.g. group keys).
    Idempotent — re-registering the same function is a no-op."""
    if fn not in _GLOBAL_SOURCES:
        _GLOBAL_SOURCES.append(fn)


def register_record_source(entity_type: str, fn: RecordSource) -> None:
    """Register a source of record-scoped principal *sets* for ``entity_type``
    (e.g. the host resolves every ``project_role:<key>`` the user holds on the
    record's project in one query). Idempotent — re-registering the same
    function is a no-op. Sources are only consulted when a record is present."""
    sources = _RECORD_SOURCES.setdefault(entity_type, [])
    if fn not in sources:
        sources.append(fn)


def _role_of(user: Any) -> Optional[str]:
    role = getattr(user, "role", None)
    if role is None:
        return None
    return getattr(role, "value", role)  # Enum -> its value; plain str passes through


def held_principals(
    user: Any, entity_type: str, record: Any, session: Any
) -> set[str]:
    """The set of principals ``user`` holds w.r.t. ``record``: their global role,
    the keys of groups they belong to (global sources), every registered
    relationship that resolves true, plus (when a record is present) the union of
    the entity's record sources (TEAMY-486). ``None`` user (anonymous) holds
    nothing. A misbehaving resolver/source is treated as not-applicable (never
    grants)."""
    held: set[str] = set()
    if user is None:
        return held
    role = _role_of(user)
    if role is not None:
        held.add(role)
    for source in _GLOBAL_SOURCES:
        try:
            held.update(source(user, session))
        except Exception:
            continue
    for (et, principal), fn in _RESOLVERS.items():
        if et != entity_type:
            continue
        try:
            if fn(user, record, session):
                held.add(principal)
        except Exception:
            continue
    if record is not None:
        for source in _RECORD_SOURCES.get(entity_type, ()):
            try:
                held.update(source(user, record, session))
            except Exception:
                continue
    return held
