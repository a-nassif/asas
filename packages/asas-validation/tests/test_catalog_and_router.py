"""assert_rules_known fail-loud behavior and the /validation/rules read endpoint."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from asas_validation import (
    Rule,
    assert_rules_known,
    build_router,
    declare_rules,
    register_fields,
)


def test_assert_rules_known_passes_and_fails_loud():
    declare_rules((Rule("m", "not_future", ("dob",), "x", "m.dob"),))
    register_fields("m", ["dob", "name"])
    assert_rules_known()  # ok

    declare_rules((Rule("m", "not_future", ("dobb",), "x", "m.typo"),))
    with pytest.raises(ValueError, match="m.typo"):
        assert_rules_known()


def test_assert_rules_known_checks_namespaced_parent_and_kind():
    declare_rules((Rule("child", "order", ("parent.start", "when"), "x", "c.r"),))
    register_fields("child", ["when"])
    register_fields("parent", ["start"])
    assert_rules_known()  # ok

    register_fields("parent", [])  # doesn't unregister; add a truly unknown parent field
    declare_rules((Rule("child", "order", ("parent.nope", "when"), "x", "c.bad"),))
    with pytest.raises(ValueError, match="parent.nope"):
        assert_rules_known()

    declare_rules((Rule("m", "sideways", ("dob",), "x", "m.kind"),))
    register_fields("m", ["dob"])
    with pytest.raises(ValueError, match="unknown kind"):
        assert_rules_known()


def test_unregistered_entity_is_treated_as_known():
    """Rules only get checked once the host opts the entity in — mirrors the engine's
    progressive-adoption stance."""
    declare_rules((Rule("later", "not_future", ("anything",), "x", "l.r"),))
    assert_rules_known()  # no registration for 'later' → passes


def _client():
    app = FastAPI()
    app.include_router(build_router())
    return TestClient(app)


def test_rules_endpoint_serves_declared_set_with_etag():
    declare_rules(
        (
            Rule("m", "not_future", ("dob",), "No future dob.", "m.dob_future"),
            Rule("p", "order", ("start", "end"), "Order.", "p.order"),
        )
    )
    client = _client()
    resp = client.get("/validation/rules")
    assert resp.status_code == 200
    assert {r["code"] for r in resp.json()} == {"m.dob_future", "p.order"}
    assert resp.json()[0]["field"] == "dob"  # serialized target for the UI

    only_m = client.get("/validation/rules", params={"entity": "m"}).json()
    assert [r["code"] for r in only_m] == ["m.dob_future"]

    etag = resp.headers["ETag"]
    assert client.get("/validation/rules", headers={"If-None-Match": etag}).status_code == 304

    # a different declared set must produce a different ETag (no stale 304s across deploys)
    declare_rules((Rule("m", "not_future", ("dob",), "No future dob.", "m.dob_future"),))
    assert client.get("/validation/rules", headers={"If-None-Match": etag}).status_code == 200
