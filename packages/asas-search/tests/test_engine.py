"""The portable composition tier: provider registry, merge/dedup, rank tiers,
group truncation, blank/unknown handling."""

import asas_search as search
from asas_search import SearchHit


def _hit(id, title, tier=search.TIER_BASE_FIELD, score=0.0, et="member"):
    return SearchHit(
        entity_type=et, id=id, title=title, url_path=f"/members/{id}",
        rank_tier=tier, rank_score=score,
    )


def test_title_tier():
    assert search.title_tier("Alice Smith", "ali") == search.TIER_TITLE_PREFIX
    assert search.title_tier("Sir Alice", "ali") == search.TIER_TITLE_CONTAINS
    assert search.title_tier("Bob", "ali") == search.TIER_BASE_FIELD


def test_search_groups_sorts_and_truncates(session):
    search.register_provider(
        "member",
        lambda s, u, q, lang, limit: [
            _hit(1, "Zed", tier=search.TIER_TITLE_PREFIX),
            _hit(2, "Alpha", tier=search.TIER_BASE_FIELD),
            _hit(3, "Beta", tier=search.TIER_TITLE_CONTAINS),
        ],
    )
    groups = search.search(session, None, "z", limit=2)
    assert [h.id for h in groups["member"]] == [1, 3]  # tier asc, truncated to 2


def test_dedup_keeps_strongest_signal(session):
    search.register_provider(
        "member", lambda s, u, q, lang, limit: [_hit(1, "A", tier=search.TIER_CONTENT, score=0.9)]
    )
    search.register_provider(
        "member", lambda s, u, q, lang, limit: [_hit(1, "A", tier=search.TIER_TITLE_PREFIX)]
    )
    groups = search.search(session, None, "a")
    assert len(groups["member"]) == 1
    assert groups["member"][0].rank_tier == search.TIER_TITLE_PREFIX


def test_blank_query_and_unknown_types(session):
    search.register_provider("member", lambda s, u, q, lang, limit: [_hit(1, "A")])
    assert search.search(session, None, "   ") == {"member": []}
    groups = search.search(session, None, "a", types={"member", "nonexistent"})
    assert set(groups) == {"member"}
