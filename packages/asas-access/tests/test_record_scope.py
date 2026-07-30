"""Record principal sources + record-scoped action checks (TEAMY-486): the
namespaced-family source, action_allowed_for semantics (floor, grants, org
scoping, resolvers + sources joining the held set), and the fail-loud rules
(unknown verb; record-scoped verb checked org-wide)."""

from types import SimpleNamespace

import pytest

import asas_access as access
from asas_access.models import ActionPermission

from conftest import make_user

# A minimal record duck: the engine never reads record attributes itself —
# resolvers/sources do.
PROJECT = SimpleNamespace(id=7, lead_id=42)


def _role_source(roles_by_member):
    """A host-style record source: member_id -> set of project_role:* principals."""

    def source(user, record, session):
        return roles_by_member.get(user.member_id, set())

    return source


def test_record_source_joins_held_principals(session):
    access.register_record_source(
        "project", _role_source({1: {"project_role:manager"}})
    )
    held = access.held_principals(make_user(member_id=1), "project", PROJECT, session)
    assert "project_role:manager" in held
    held = access.held_principals(make_user(member_id=2), "project", PROJECT, session)
    assert "project_role:manager" not in held


def test_record_source_skipped_without_record_and_idempotent_registration(session):
    src = _role_source({1: {"project_role:manager"}})
    access.register_record_source("project", src)
    access.register_record_source("project", src)  # no-op, not a double call
    from asas_access import principals

    assert len(principals._RECORD_SOURCES["project"]) == 1
    # No record (the org-wide action scope) => sources never fire.
    held = access.held_principals(make_user(member_id=1), "project", None, session)
    assert "project_role:manager" not in held


def test_misbehaving_record_source_never_grants(session):
    def boom(user, record, session):
        raise RuntimeError("host bug")

    access.register_record_source("project", boom)
    access.register_record_source(
        "project", _role_source({1: {"project_role:manager"}})
    )
    held = access.held_principals(make_user(member_id=1), "project", PROJECT, session)
    assert "project_role:manager" in held  # the healthy source still contributes


def test_action_allowed_for_grants_by_record_principal(session):
    access.register_actions(["project.manage"], record_scoped=True)
    access.seed_action_permissions(
        session, [("project.manage", "project_role:manager")]
    )
    access.register_record_source(
        "project", _role_source({1: {"project_role:manager"}})
    )
    assert access.action_allowed_for(
        session, make_user(member_id=1), "project.manage", "project", PROJECT
    )
    assert not access.action_allowed_for(
        session, make_user(member_id=2), "project.manage", "project", PROJECT
    )
    assert not access.action_allowed_for(
        session, None, "project.manage", "project", PROJECT
    )  # anonymous


def test_action_allowed_for_admin_floor_and_relationship_resolver(session):
    access.register_actions(["project.manage"], record_scoped=True)
    # Floor: admin needs no rows.
    assert access.action_allowed_for(
        session, make_user("admin"), "project.manage", "project", PROJECT
    )
    # A boolean relationship resolver joins the same union as sources.
    access.seed_action_permissions(session, [("project.manage", "project_lead")])
    access.register_resolver(
        "project",
        "project_lead",
        lambda user, record, s: user.member_id == record.lead_id,
    )
    assert access.action_allowed_for(
        session, make_user(member_id=42), "project.manage", "project", PROJECT
    )
    assert not access.action_allowed_for(
        session, make_user(member_id=1), "project.manage", "project", PROJECT
    )


def test_action_allowed_for_respects_org_scoped_rows(session):
    access.register_actions(["project.manage"], record_scoped=True)
    session.add(
        ActionPermission(
            permission="project.manage", principal="project_role:manager", org_id=2
        )
    )
    session.commit()
    access.invalidate_action_cache()
    access.register_record_source(
        "project", _role_source({1: {"project_role:manager"}})
    )
    assert not access.action_allowed_for(
        session, make_user(member_id=1, org_id=1), "project.manage", "project", PROJECT
    )
    assert access.action_allowed_for(
        session, make_user(member_id=1, org_id=2), "project.manage", "project", PROJECT
    )


def test_record_scoped_verb_fails_loud_on_org_wide_check(session):
    access.register_actions(["project.manage"], record_scoped=True)
    with pytest.raises(ValueError, match="record-scoped"):
        access.action_allowed(session, make_user("admin"), "project.manage")
    assert access.record_scoped_actions() == {"project.manage"}


def test_action_allowed_for_unknown_verb_raises_and_org_verbs_still_work(session):
    with pytest.raises(ValueError, match="unknown action permission"):
        access.action_allowed_for(
            session, make_user("admin"), "never.registered", "project", PROJECT
        )
    # An org-wide verb checked with record context resolves fine (grants simply
    # never name record principals).
    access.register_actions(["team.create"])
    access.seed_action_permissions(session, [("team.create", "leads")])
    access.register_global_source(lambda user, s: {"leads"})
    assert access.action_allowed_for(
        session, make_user("member"), "team.create", "project", PROJECT
    )
