"""Group key namespace guard, host reservations, and system-group seeding."""

import pytest
from sqlmodel import select

import asas_access as access
from asas_access.models import AccessGroup


def test_key_format_guard():
    access.validate_group_key("people_ops")
    for bad in ("", "Caps", "1starts_with_digit", "has-dash", "x" * 65):
        with pytest.raises(ValueError, match="invalid group key"):
            access.validate_group_key(bad)


def test_reserved_namespace_includes_base_and_host():
    with pytest.raises(ValueError, match="reserved principal"):
        access.validate_group_key(access.SELF)
    with pytest.raises(ValueError, match="reserved principal"):
        access.validate_group_key("admin")
    # Host history joins the reserved set (e.g. Teamy's retired roles).
    access.validate_group_key("hr")  # not reserved until the host says so
    access.reserve_principals({"hr"})
    with pytest.raises(ValueError, match="reserved principal"):
        access.validate_group_key("hr")


def test_ensure_system_groups_idempotent(session):
    catalog = {"people_ops": "People Ops", "leads": "Leads"}
    access.ensure_system_groups(session, 1, catalog)
    session.commit()
    access.ensure_system_groups(session, 1, catalog)  # second run adds nothing
    session.commit()
    rows = session.exec(select(AccessGroup).where(AccessGroup.org_id == 1)).all()
    assert {g.key for g in rows} == {"people_ops", "leads"}
    assert all(g.is_system for g in rows)
    # Another org gets its own copies.
    access.ensure_system_groups(session, 2, catalog)
    session.commit()
    assert access.group_by_key(session, 2, "leads") is not None
    assert access.group_by_key(session, 2, "leads").id != access.group_by_key(session, 1, "leads").id
