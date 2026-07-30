"""Semantic retrieval over the deep-content index (Phase 3, WXL-162).

pgvector KNN over ``search_document.embedding`` — the same rows, corpora, and sync
machinery as Phase 2 FTS (``fts.py``); vectors piggyback on the existing ``IndexDoc``
flow. Postgres-tier only, raw SQL, self-contained like the rest of the package.

Key properties (see also WXL-168 — the future clearance-model epic):

- **Vectors are permission-agnostic content copies.** Visibility is applied at query
  time by the entity resolvers (exactly like the lexical arm), so an access-control
  overhaul changes the filter, never the embeddings.
- **Embed after commit, not in the flush.** The FTS sync events insert rows with
  ``embedding`` NULL; :func:`embed_pending` fills NULLs (and rows embedded under a
  different model — a provider/model switch re-embeds, vector spaces never mix).
  Wiring runs it post-commit and at startup.
- **Graceful degradation.** Unconfigured or failing provider ⇒ rows stay lexically
  searchable and queries fall back to pure-lexical; nothing else breaks.
"""

import logging
from typing import Any, List, NamedTuple, Optional, Sequence

from sqlalchemy import text

from .embeddings import EmbeddingProvider

_log = logging.getLogger(__name__)

# The active provider, set by app wiring (None ⇒ semantic tier off, lexical only).
_provider: Optional[EmbeddingProvider] = None

# Per-process cache of query embeddings: one /search request fans out to several
# entity-type providers that all embed the same query; only the first pays the call.
_query_cache: dict[str, List[float]] = {}
_QUERY_CACHE_MAX = 256


def configure(provider: Optional[EmbeddingProvider]) -> None:
    global _provider
    _provider = provider
    _query_cache.clear()


def is_configured() -> bool:
    return _provider is not None


def _vec(v: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


# ---------------------------------------------------------------------------
# Embed-on-write sweep
# ---------------------------------------------------------------------------

# IS DISTINCT FROM (not <>) so NULL-model rows are always pending too.
_PENDING = text(
    """
    SELECT id, content FROM search_document
    WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM :model
    ORDER BY id LIMIT :cap
    """
)
_HAS_PENDING = text(
    """
    SELECT 1 FROM search_document
    WHERE embedding IS NULL OR embedding_model IS DISTINCT FROM :model
    LIMIT 1
    """
)
_SET = text(
    """
    UPDATE search_document
    SET embedding = CAST(:vec AS vector), embedding_model = :model
    WHERE id = :id
    """
)

_SWEEP_BATCH = 256
# Stay under provider per-input token caps (~8k tokens); chars/4 ≈ tokens.
_MAX_CHARS = 30_000


def has_pending(conn: Any) -> bool:
    if _provider is None:
        return False
    return conn.execute(_HAS_PENDING, {"model": _provider.model}).first() is not None


def embed_pending(conn: Any) -> int:
    """Fill missing/stale embeddings; returns rows embedded. Caller owns the
    transaction; provider errors propagate (callers degrade gracefully)."""
    if _provider is None:
        return 0
    total = 0
    while True:
        rows = conn.execute(
            _PENDING, {"model": _provider.model, "cap": _SWEEP_BATCH}
        ).all()
        if not rows:
            return total
        vectors = _provider.embed([r.content[:_MAX_CHARS] for r in rows])
        for row, vector in zip(rows, vectors):
            conn.execute(
                _SET, {"id": row.id, "vec": _vec(vector), "model": _provider.model}
            )
        total += len(rows)


# ---------------------------------------------------------------------------
# KNN query
# ---------------------------------------------------------------------------

# KNN alone returns the k nearest rows however unrelated; the distance cut keeps rare
# queries from surfacing arbitrary records (cosine distance: 0 identical, 1
# orthogonal). 0.7 is a pragmatic default for text-embedding-3 — tune with real data.
MAX_DISTANCE = 0.7

# Best row per entity (DISTINCT ON), then nearest entities first — the same shape as
# fts._QUERY. embedding_model = :model keeps distances within one vector space.
_KNN = text(
    """
    SELECT entity_id, context, source, distance FROM (
        SELECT DISTINCT ON (entity_id)
               entity_id,
               context,
               source,
               embedding <=> CAST(:qvec AS vector) AS distance
        FROM search_document
        WHERE entity_type = :entity_type
          AND org_id = :org_id
          AND embedding IS NOT NULL
          AND embedding_model = :model
        ORDER BY entity_id, distance
    ) best
    WHERE distance < :max_distance
    ORDER BY distance
    LIMIT :k
    """
)


class SemanticRow(NamedTuple):
    entity_id: int
    context: str
    source: str


def _query_vector(q: str) -> Optional[List[float]]:
    if _provider is None:
        return None
    cached = _query_cache.get(q)
    if cached is not None:
        return cached
    vector = _provider.embed([q])[0]
    if len(_query_cache) >= _QUERY_CACHE_MAX:
        _query_cache.clear()
    _query_cache[q] = vector
    return vector


def knn(
    session: Any, entity_type: str, q: str, k: int, org_id: int
) -> List[SemanticRow]:
    """Nearest visible-corpus rows for ``q`` within one org (WXL-238),
    best-per-entity, nearest first. Empty when unconfigured or the provider
    fails — the hybrid provider then degrades to pure-lexical."""
    if _provider is None:
        return []
    try:
        qvec = _query_vector(q)
    except Exception:
        _log.warning("query embedding failed; falling back to lexical", exc_info=True)
        return []
    rows = session.execute(
        _KNN,
        {
            "qvec": _vec(qvec),
            "entity_type": entity_type,
            "org_id": org_id,
            "model": _provider.model,
            "max_distance": MAX_DISTANCE,
            "k": k,
        },
    ).all()
    return [SemanticRow(r.entity_id, r.context, r.source) for r in rows]
