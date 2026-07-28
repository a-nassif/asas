# asas-search

A cross-entity search engine: the host registers one or more **providers** per
searchable entity type (`(session, user, q, lang, limit) -> [SearchHit]`); the
engine merges, dedupes (strongest signal per record), rank-tiers, and truncates
each group. Visibility is the provider's job — providers must match only fields
every viewer of the record may read (search must never become an oracle for
hidden data).

On top of the portable tier, an optional **Postgres deep-content tier**:

- `fts` — one raw-SQL side table (`search_document`) with a bilingual
  english+arabic tsvector; the host supplies *extractors* (its rows →
  `IndexDoc`) and *resolvers* (matched entity ids → visible titles/urls) and
  keeps the index fresh via its own ORM events. `fts.make_provider` builds a
  provider that fuses lexical FTS with semantic KNN via Reciprocal Rank Fusion.
- `semantic` / `embeddings` — pgvector KNN over the same rows, filled
  after-commit by `semantic.embed_pending`; one OpenAI-compatible adapter
  (`base_url` selects OpenAI/Azure/local). Vector spaces never mix (rows carry
  `embedding_model`); a provider/model switch re-embeds automatically.
  **Unconfigured ⇒ pure-lexical; on SQLite ⇒ portable tier only. Nothing breaks.**

Table-owning variant of the Asas host contract with a **dialect-branched**
chain: `migrate(engine)` (version table `alembic_version_asas_search`,
adopt-or-create) creates `search_document` on Postgres only; on SQLite it
records the version and creates nothing.

```python
import asas_search as search

# boot (host wiring)
search.migrate(engine)
search.register_provider("member", member_provider)          # portable ilike tier
if engine.dialect.name == "postgresql":                      # deep tier
    search.fts.register_extractor("experience", extract_experiences)
    search.register_provider("member", search.fts.make_provider("member", resolve_members, org_of))
    search.semantic.configure(search.embeddings.create_provider("openai", key, model, base_url))

# request path
groups = search.search(session, user, q, types={"member", "team"}, limit=5)
```

See the repo README for the full contract. Extracted from Teamy (search epic
WXL-44 phases 1–3; extraction epic TEAMY-466 / design record 0017 — full search
design in Teamy's decision record 0006).
