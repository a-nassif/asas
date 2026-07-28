"""Action-permission engine: the admin floor, unconfigured-verb default,
unknown-verb fail-loud, org scoping, granted_principals, seed validation."""

import pytest
from sqlmodel import select

import asas_access as access
from asas_access.models import ActionPermission

from conftest import make_user


def test_unconfigured_verb_is_admin_only(session):
    access.register_actions(["team.create"])
    assert access.action_allowed(session, make_user("admin"), "team.create")
    assert not access.action_allowed(session, make_user("member"), "team.create")
    assert not access.action_allowed(session, None, "team.create")  # anonymous


def test_unknown_verb_raises(session):
    with pytest.raises(ValueError, match="unknown action permission"):
        access.action_allowed(session, make_user("admin"), "never.registered")
    with pytest.raises(ValueError, match="unknown action permission"):
        access.granted_principals(session, "never.registered")


def test_grant_rows_allow_and_union_with_groups(session):
    access.register_actions(["team.create"])
    access.seed_action_permissions(session, [("team.create", "leads")])
    assert not access.action_allowed(session, make_user("member"), "team.create")
    access.register_global_source(lambda user, s: {"leads"})
    assert access.action_allowed(session, make_user("member"), "team.create")


def test_org_scoped_grants_do_not_leak(session):
    access.register_actions(["team.create"])
    session.add(ActionPermission(permission="team.create", principal="member", org_id=2))
    session.commit()
    access.invalidate_action_cache()
    assert not access.action_allowed(session, make_user("member", org_id=1), "team.create")
    assert access.action_allowed(session, make_user("member", org_id=2), "team.create")


def test_granted_principals_excludes_floor_and_scopes(session):
    access.register_actions(["team.create"])
    access.seed_action_permissions(session, [("team.create", "leads")])
    session.add(ActionPermission(permission="team.create", principal="member", org_id=2))
    session.commit()
    access.invalidate_action_cache()
    assert access.granted_principals(session, "team.create") == {"leads"}
    assert access.granted_principals(session, "team.create", org_id=2) == {"leads", "member"}


def test_seed_is_idempotent_and_validates_verbs(session):
    access.register_actions(["team.create"])
    access.seed_action_permissions(session, [("team.create", "leads")])
    access.seed_action_permissions(session, [("team.create", "leads")])
    assert len(session.exec(select(ActionPermission)).all()) == 1
    with pytest.raises(ValueError, match="unknown verb"):
        access.seed_action_permissions(session, [("team.typo", "leads")])
