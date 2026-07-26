"""Read-only endpoint exposing the declared rule set so clients can enforce the *same*
constraints locally — one source of truth for what the rules are. ETag-cached because
the rules are static per deploy. Built by a factory for contract consistency; it needs
no session dependency (this module has no database)."""

import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Header, Response

from .rules import Rule, declared_rules, rules_for


def _serialize(rules: list[Rule]) -> list[dict]:
    return [
        {
            "kind": r.kind,
            "fields": list(r.fields),
            "field": r.target,
            "code": r.code,
            "message": r.message,
            "params": r.params,
        }
        for r in rules
    ]


def _etag() -> str:
    # Weak ETag (W/"…") on purpose: compression proxies (e.g. Render's edge) downgrade
    # strong ETags to weak on gzipped responses, so a strong tag never round-trips —
    # the client echoes W/"…" and revalidation always misses. Emitting the weak form
    # makes the round trip exact (the lookups module's ETag convention).
    blob = json.dumps(_serialize(list(declared_rules())), sort_keys=True)
    return 'W/"' + hashlib.md5(blob.encode()).hexdigest() + '"'


def build_router() -> APIRouter:
    """Build the ``/validation/rules`` read router. The host applies any auth guards
    when including it (composition-time, like every Asas router)."""

    router = APIRouter(prefix="/validation", tags=["validation"])

    @router.get("/rules")
    def get_rules(
        response: Response,
        entity: Optional[str] = None,
        if_none_match: Optional[str] = Header(default=None),
    ):
        """Return the validation rules, optionally filtered to one ``entity``."""
        etag = _etag()
        if if_none_match == etag:
            return Response(status_code=304, headers={"ETag": etag})
        response.headers["ETag"] = etag
        rules = rules_for(entity) if entity else list(declared_rules())
        return _serialize(rules)

    return router
