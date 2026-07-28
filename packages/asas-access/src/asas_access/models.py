"""Access-control tables. Kept separate from ``app.models`` so the package stays
self-contained (no member/app imports) and independently extractable."""

from typing import Optional

from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel


class FieldPermission(SQLModel, table=True):
    """One *allowed* (entity_type, field, action, principal) grant — pure config data.

    A field with **no** rows for an action keeps the caller's baseline rule. Rows switch
    that field to an explicit allowlist of principals (plus the implicit ``admin`` floor).
    ``principal`` is a global role or a relationship principal (see ``principals.py``);
    ``action`` is ``"view"`` or ``"edit"``.
    """

    __tablename__ = "field_permission"
    __table_args__ = (
        # org_id is part of the identity: an org-scoped override row must not
        # collide with the platform default for the same grant (TEAMY-454).
        UniqueConstraint(
            "entity_type",
            "field",
            "action",
            "principal",
            "org_id",
            name="uq_field_permission",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # Per-org override slot (WXL-241, dormant): NULL = platform default. Resolution
    # activates with the first per-org config consumer; seeds stay global.
    org_id: Optional[int] = Field(default=None, index=True)
    entity_type: str = Field(index=True)
    field: str
    action: str  # "view" | "edit"
    principal: str


class ActionPermission(SQLModel, table=True):
    """One *allowed* (permission, principal) grant for an org-wide action verb
    (TEAMY-452) — pure config data, the action-level sibling of ``FieldPermission``.

    ``permission`` is a cataloged verb (``team.create``, ``audit.view``, …) registered
    via ``register_actions``; ``principal`` is a global role today (groups join the
    same namespace with TEAMY-453). A verb with **no** rows is admin-only (the
    implicit floor); rows form an explicit allowlist on top of that floor.
    """

    __tablename__ = "action_permission"
    __table_args__ = (
        UniqueConstraint(
            "permission", "principal", "org_id", name="uq_action_permission"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    # Per-org override slot, dormant — mirrors FieldPermission (WXL-241).
    org_id: Optional[int] = Field(default=None, index=True)
    permission: str = Field(index=True)
    principal: str


class AccessGroup(SQLModel, table=True):
    """An org-wide functional bundle (TEAMY-453) — the third principal source.

    ``key`` is the **stable principal string** grant rows reference (lookups house
    rule: codes are stable, labels may change) — renaming a group touches ``name``
    only, never the grants. Keys are validated against the reserved principal
    namespace (roles + relationship principals) fail-loud at create/seed time.
    ``is_system`` marks seeded groups (People Ops, Leads): rename-only, no delete.
    """

    __tablename__ = "access_group"
    __table_args__ = (
        UniqueConstraint("org_id", "key", name="uq_access_group_org_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    key: str = Field(index=True)
    name: str
    is_system: bool = Field(default=False)


class AccessGroupMembership(SQLModel, table=True):
    """Membership of one org membership in one group. Grants nothing by itself —
    a member's effective access is the union of what their groups' grant rows
    confer, resolved at request time (never materialized into tokens/indexes)."""

    __tablename__ = "access_group_membership"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "org_membership_id", name="uq_access_group_membership"
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    group_id: int = Field(foreign_key="access_group.id", index=True)
    # Plain int (no FK) — the package never imports app models; app-side wiring
    # owns the join to org_membership (access_wiring._group_keys).
    org_membership_id: int = Field(index=True)
