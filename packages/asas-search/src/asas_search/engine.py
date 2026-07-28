"""Generic cross-entity search engine (epic WXL-44; design in Teamy DR 0006).

Self-contained for later extraction (like ``lookups``/``access``/``validation``): this
package must never import member/app models. App code registers one *provider* per
searchable entity type in ``the host's search wiring`` (called from ``db.init_db``); the
engine only composes them.

Provider contract — ``(session, user, q, lang, limit) -> list[SearchHit]``:

- return only hits the requesting user may see: visibility is the provider's job, the
  engine has no entity semantics;
- match only against fields every viewer of the record may read — never
  redactable/restricted fields (search must not become an oracle for hidden data);
- set ``rank_tier`` (``TIER_*`` / ``title_tier``) so heuristic ordering works without a
  scoring engine; the engine sorts and truncates each group.

Phase 1 providers are portable ``ilike`` SQL (identical on SQLite and Postgres). Later
engines (Postgres FTS deep-content search, WXL-150) swap providers behind this same
registry; callers never change.
"""

from typing import Any, Callable, Optional

from pydantic import BaseModel

# Rank tiers, best (lowest) first: how directly the hit's *title* matched, vs. a match
# in another base field, vs. one found through a child/related record, vs. a ranked
# full-text match inside long prose (Phase 2 deep-content search).
TIER_TITLE_PREFIX = 0
TIER_TITLE_CONTAINS = 1
TIER_BASE_FIELD = 2
TIER_RELATED = 3
TIER_CONTENT = 4


class SearchHit(BaseModel):
    entity_type: str
    id: int
    title: str
    subtitle: Optional[str] = None
    # Why the record matched when the title/subtitle don't show it,
    # e.g. "via experience: Aramco — Senior Engineer" or an FTS snippet.
    match_context: Optional[str] = None
    # A short state label the provider wants shown next to the title (e.g.
    # "Provisional" for an unclaimed imported member, TEAMY-415). Deliberately an
    # opaque string: the engine stays entity-agnostic and must never learn what a
    # member lifecycle is — providers decide what, if anything, to surface.
    badge: Optional[str] = None
    url_path: str
    rank_tier: int = TIER_BASE_FIELD
    # Relevance within a tier (only deep-content providers set it; ts_rank-style,
    # higher is better). Sorting is (tier asc, score desc, title).
    rank_score: float = 0.0


Provider = Callable[[Any, Any, str, str, int], list[SearchHit]]

# Multiple providers may serve one entity type (Phase 1 structured matching + the
# Postgres-tier deep-content provider); their hits are merged and deduped per id.
_PROVIDERS: dict[str, list[Provider]] = {}


def register_provider(entity_type: str, provider: Provider) -> None:
    _PROVIDERS.setdefault(entity_type, []).append(provider)


def registered_types() -> list[str]:
    return list(_PROVIDERS)


def title_tier(title: str, q: str) -> int:
    """Tier for a hit whose *title* may itself contain the query; falls through to
    ``TIER_BASE_FIELD`` when it doesn't (the provider matched something else)."""
    hay = (title or "").lower()
    needle = q.lower()
    if hay.startswith(needle):
        return TIER_TITLE_PREFIX
    if needle in hay:
        return TIER_TITLE_CONTAINS
    return TIER_BASE_FIELD


def search(
    session: Any,
    user: Any,
    q: str,
    *,
    lang: str = "en",
    types: Optional[set[str]] = None,
    limit: int = 5,
) -> dict[str, list[SearchHit]]:
    """Run every registered (or requested) provider and return hits grouped by entity
    type, each group rank-sorted and truncated to ``limit``. Unknown ``types`` entries
    are ignored; a blank query returns empty groups."""
    needle = (q or "").strip()
    wanted = [t for t in _PROVIDERS if types is None or t in types]
    results: dict[str, list[SearchHit]] = {t: [] for t in wanted}
    if not needle:
        return results
    for entity_type in wanted:
        merged: dict[int, SearchHit] = {}
        for provider in _PROVIDERS[entity_type]:
            for hit in provider(session, user, needle, lang, limit):
                best = merged.get(hit.id)
                # Dedup across providers: keep the strongest signal per record.
                if best is None or (hit.rank_tier, -hit.rank_score) < (
                    best.rank_tier,
                    -best.rank_score,
                ):
                    merged[hit.id] = hit
        hits = sorted(
            merged.values(),
            key=lambda h: (h.rank_tier, -h.rank_score, h.title.lower()),
        )
        results[entity_type] = hits[:limit]
    return results
