"""Record visibility: public passes, private gates on the admin floor,
registered relationship viewers, and the record.view_private verb."""

from types import SimpleNamespace

import asas_access as access

from conftest import make_user


def _team(visibility):
    return SimpleNamespace(id=5, visibility=visibility, lead_id=9)


def test_public_and_unmarked_records_visible_to_all(session):
    access.register_actions([access.VIEW_PRIVATE])
    assert access.can_view_record(session, None, "team", _team(access.PUBLIC))
    assert access.can_view_record(session, None, "team", SimpleNamespace(id=1))  # no attr


def test_private_gates_on_floor_viewers_and_grant(session):
    access.register_actions([access.VIEW_PRIVATE])
    team = _team(access.PRIVATE)
    assert not access.can_view_record(session, make_user("member"), "team", team)
    assert not access.can_view_record(session, None, "team", team)
    assert access.can_view_record(session, make_user("admin"), "team", team)
    # Registered relationship viewer (the team's lead).
    access.register_resolver(
        "team", access.TEAM_LEAD, lambda user, rec, s: user.member_id == rec.lead_id
    )
    access.register_private_viewers("team", {access.TEAM_LEAD})
    assert access.can_view_record(session, make_user("member", member_id=9), "team", team)
    assert not access.can_view_record(session, make_user("member", member_id=8), "team", team)
    # The org-wide view_private grant (config, not code).
    access.seed_action_permissions(session, [(access.VIEW_PRIVATE, "people_ops")])
    access.register_global_source(lambda user, s: {"people_ops"})
    assert access.can_view_record(session, make_user("member", member_id=8), "team", team)
