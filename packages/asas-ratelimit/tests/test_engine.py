"""Token-bucket engine: depletion/refill via an injected clock, unknown-rule
and disabled-mode allowance, the 429 + Retry-After check, bucket pruning, and
the overrides-string parser. Engine tests ported from Teamy's
tests/test_ratelimit.py (TEAMY-334) with the extraction (TEAMY-473)."""

import uuid

import pytest
from fastapi import HTTPException

import asas_ratelimit as ratelimit


@pytest.fixture(autouse=True)
def _clean_engine():
    """Each test starts with no rules, no counters, defaults restored."""
    ratelimit.reset()
    ratelimit.configure(enabled=True)
    yield
    ratelimit.reset()
    ratelimit.configure(enabled=True)


def test_bucket_depletes_and_refills():
    ratelimit.declare(ratelimit.Rule(name="t.basic", limit=3, window_seconds=60))
    now = [1000.0]
    ratelimit.configure(enabled=True, clock=lambda: now[0])
    key = uuid.uuid4().hex
    assert all(ratelimit.allow("t.basic", key)[0] for _ in range(3))
    allowed, retry = ratelimit.allow("t.basic", key)
    assert not allowed and retry > 0
    now[0] += 20.0  # one token refilled (3/60s = 1 per 20s)
    assert ratelimit.allow("t.basic", key)[0]
    assert not ratelimit.allow("t.basic", key)[0]


def test_burst_caps_the_bucket():
    """burst < limit: only `burst` tokens may be spent at once, refill still
    runs at limit/window."""
    ratelimit.declare(
        ratelimit.Rule(name="t.burst", limit=60, window_seconds=60, burst=2)
    )
    now = [0.0]
    ratelimit.configure(enabled=True, clock=lambda: now[0])
    key = uuid.uuid4().hex
    assert ratelimit.allow("t.burst", key)[0]
    assert ratelimit.allow("t.burst", key)[0]
    assert not ratelimit.allow("t.burst", key)[0]
    now[0] += 100.0  # plenty of refill time — capacity still caps at burst
    assert ratelimit.allow("t.burst", key)[0]
    assert ratelimit.allow("t.burst", key)[0]
    assert not ratelimit.allow("t.burst", key)[0]


def test_keys_are_independent():
    ratelimit.declare(ratelimit.Rule(name="t.keys", limit=1, window_seconds=60))
    assert ratelimit.allow("t.keys", "alice")[0]
    assert not ratelimit.allow("t.keys", "alice")[0]
    assert ratelimit.allow("t.keys", "bob")[0]  # a spent bucket is per-key


def test_unknown_rule_and_disabled_mode_allow():
    assert ratelimit.allow("t.never_declared", "k")[0]
    ratelimit.declare(ratelimit.Rule(name="t.off", limit=1, window_seconds=60))
    key = uuid.uuid4().hex
    ratelimit.check("t.off", key)
    ratelimit.configure(enabled=False)
    for _ in range(5):
        ratelimit.check("t.off", key)  # would 429 if enforced


def test_check_raises_429_with_retry_after():
    ratelimit.declare(ratelimit.Rule(name="t.raise", limit=1, window_seconds=60))
    key = uuid.uuid4().hex
    ratelimit.check("t.raise", key)
    with pytest.raises(HTTPException) as exc:
        ratelimit.check("t.raise", key)
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) >= 1


def test_clear_counters_keeps_rules():
    ratelimit.declare(ratelimit.Rule(name="t.clear", limit=1, window_seconds=60))
    key = uuid.uuid4().hex
    assert ratelimit.allow("t.clear", key)[0]
    assert not ratelimit.allow("t.clear", key)[0]
    ratelimit.clear_counters()
    assert "t.clear" in ratelimit.rules()
    assert ratelimit.allow("t.clear", key)[0]  # fresh bucket


def test_prune_drops_stale_buckets_beyond_bound(monkeypatch):
    """Past _MAX_BUCKETS, stale (window-elapsed) and orphaned buckets are
    dropped — an attacker cycling keys can't grow memory unboundedly."""
    monkeypatch.setattr(ratelimit, "_MAX_BUCKETS", 5)
    ratelimit.declare(ratelimit.Rule(name="t.prune", limit=1, window_seconds=10))
    now = [0.0]
    ratelimit.configure(enabled=True, clock=lambda: now[0])
    for i in range(6):
        ratelimit.allow("t.prune", f"key-{i}")
    now[0] += 11.0  # all buckets are now stale
    ratelimit.allow("t.prune", "trigger")  # exceeds the bound -> prune runs
    assert len(ratelimit._buckets) <= 2  # stale ones dropped


def test_parse_overrides_accepts_good_and_skips_malformed():
    parsed = ratelimit.parse_overrides(
        "auth.login.ip=10/3600, chat.user=5/60 ,broken,also=bad/entry"
    )
    assert parsed["auth.login.ip"] == (10, 3600.0)
    assert parsed["chat.user"] == (5, 60.0)
    assert "broken" not in parsed
    assert len(parsed) == 2


def test_parse_overrides_empty_string():
    assert ratelimit.parse_overrides("") == {}
