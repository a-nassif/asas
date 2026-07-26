"""Framework glue: turn engine ``Violation``s into FastAPI's native 422 envelope
(``{"detail": [{"loc", "msg", "type"}, ...]}``) so the frontend handles our semantic
constraint errors and Pydantic's body-shape errors through one code path."""

from typing import Any, Optional

from fastapi import HTTPException

from .engine import Violation, evaluate


def to_http(violations: list[Violation]) -> HTTPException:
    detail = [
        {"loc": ["body", v.field], "msg": v.message, "type": f"value_error.{v.code}"}
        for v in violations
    ]
    return HTTPException(status_code=422, detail=detail)


def raise_if_invalid(
    entity: str,
    record: Optional[Any],
    changes: dict[str, Any],
    context: Optional[dict[str, Any]] = None,
) -> None:
    """Evaluate the entity's rules for this edit and raise a 422 if anything fails.
    ``context`` carries related-record values for cross-entity rules (namespaced fields).
    Call in create/update routers right before applying the changes."""
    violations = evaluate(entity, record, changes, context)
    if violations:
        raise to_http(violations)
