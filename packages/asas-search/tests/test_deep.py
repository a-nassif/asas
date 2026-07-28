"""The Postgres deep-content tier: index upsert/rebuild, bilingual FTS query
through make_provider, semantic embed sweep + KNN, RRF fusion, and lexical
degradation when unconfigured. All PG-gated (the tier does not exist on SQLite)."""

from sqlalchemy import text

import asas_search as search
from asas_search import fts, semantic

from conftest import FakeEmbeddings, requires_postgres


def _doc(source_id, content, *, entity_id=1, org=1, source="experience"):
    return fts.IndexDoc(
        entity_type="member", entity_id=entity_id, source=source,
        source_id=source_id, content=content,
        context=f"via {source}", org_id=org,
    )


def _resolver(visible):
    def resolve(session, user, ids):
        return {
            i: (f"Member {i}", None, f"/members/{i}") for i in ids if i in visible
        }
    return resolve


@requires_postgres
def test_upsert_query_and_visibility(session):
    with session.bind.begin() as conn:
        fts.upsert(conn, _doc(1, "Led the Aramco refinery data migration", entity_id=1))
        fts.upsert(conn, _doc(2, "Organized the annual bake sale", entity_id=2))
    provider = fts.make_provider("member", _resolver({1, 2}), lambda s, u: 1)
    hits = provider(session, None, "refinery migration", "en", 5)
    assert [h.id for h in hits] == [1]
    assert "refinery" in hits[0].match_context
    # A viewer who may not see member 1 gets nothing (resolver omits the id).
    provider = fts.make_provider("member", _resolver(set()), lambda s, u: 1)
    assert provider(session, None, "refinery", "en", 5) == []


@requires_postgres
def test_org_scoping_fails_closed(session):
    with session.bind.begin() as conn:
        fts.upsert(conn, _doc(1, "confidential redline analysis", org=2))
    provider = fts.make_provider("member", _resolver({1}), lambda s, u: 1)
    assert provider(session, None, "redline", "en", 5) == []  # other org's rows
    provider = fts.make_provider("member", _resolver({1}), lambda s, u: None)
    assert provider(session, None, "redline", "en", 5) == []  # no org context


@requires_postgres
def test_upsert_replaces_and_empty_deletes(session):
    with session.bind.begin() as conn:
        fts.upsert(conn, _doc(1, "original text"))
        fts.upsert(conn, _doc(1, "replacement text"))
    assert fts.count(session) == 1
    row = session.execute(text("SELECT content FROM search_document")).one()
    assert row.content == "replacement text"
    with session.bind.begin() as conn:
        fts.upsert(conn, _doc(1, "   "))  # empty content = plain delete
    assert fts.count(session) == 0


@requires_postgres
def test_rebuild_from_extractors(session):
    fts.register_extractor(
        "experience", lambda s: [_doc(1, "alpha"), _doc(2, "beta", entity_id=2)]
    )
    assert fts.rebuild(session) == 2
    assert fts.count(session) == 2


@requires_postgres
def test_embed_pending_and_semantic_fusion(session):
    semantic.configure(FakeEmbeddings())
    with session.bind.begin() as conn:
        fts.upsert(conn, _doc(1, "kubernetes cluster operations", entity_id=1))
        fts.upsert(conn, _doc(2, "watercolor painting workshops", entity_id=2))
    with session.bind.begin() as conn:
        assert semantic.has_pending(conn)
        assert semantic.embed_pending(conn) == 2
        assert not semantic.has_pending(conn)
    # Exact-content query embeds identically -> distance 0 -> nearest-first.
    # (Low-dim fake vectors may put the other row inside the distance cut too;
    # the contract is ordering, not exclusivity.)
    rows = semantic.knn(session, "member", "kubernetes cluster operations", 5, 1)
    assert rows and rows[0].entity_id == 1
    # The fused provider ranks the lexical+semantic double hit first, one row per
    # entity (RRF: found by both arms outranks found by one).
    provider = fts.make_provider("member", _resolver({1, 2}), lambda s, u: 1)
    hits = provider(session, None, "kubernetes cluster operations", "en", 5)
    assert hits[0].id == 1
    assert len([h for h in hits if h.id == 1]) == 1


@requires_postgres
def test_unconfigured_semantic_degrades_to_lexical(session):
    with session.bind.begin() as conn:
        fts.upsert(conn, _doc(1, "terraform infrastructure modules"))
    assert not semantic.is_configured()
    provider = fts.make_provider("member", _resolver({1}), lambda s, u: 1)
    assert [h.id for h in provider(session, None, "terraform", "en", 5)] == [1]


def test_embeddings_factory_validates():
    import pytest

    from asas_search import embeddings

    with pytest.raises(RuntimeError, match="unknown EMBEDDING_PROVIDER"):
        embeddings.create_provider("gcp", "key", "model", "http://x")
    with pytest.raises(RuntimeError, match="missing API key"):
        embeddings.create_provider("openai", "", "model", "http://x")
