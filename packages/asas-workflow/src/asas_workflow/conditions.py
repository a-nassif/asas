"""Structured transition conditions — {"all"/"any": [{field, op, value}, …]}.

No expression strings, no eval (owner ruling 2026-07-10): conditions are data,
validatable at definition time, portable across engines. Fields are dotted paths
into instance.data (e.g. "changes.milestone_shift_days", "nodes.review.verdict").

Missing field values make a clause False (never an error): a condition over data a
system node hasn't produced yet simply doesn't match, and the default/else branch
(condition=None, required by validate_definition) catches the walk.
"""

from typing import Any, Optional

from .models import get_path

OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "in", "contains", "is_null")


def _clause(data: dict, clause: dict) -> bool:
    field = clause["field"]
    op = clause["op"]
    expected = clause.get("value")
    actual = get_path(data, field)

    if op == "is_null":
        # value True (default) asserts null; value False asserts present.
        want_null = True if expected is None else bool(expected)
        return (actual is None) == want_null
    if actual is None:
        return False
    try:
        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "gt":
            return actual > expected
        if op == "gte":
            return actual >= expected
        if op == "lt":
            return actual < expected
        if op == "lte":
            return actual <= expected
        if op == "in":
            return actual in (expected or [])
        if op == "contains":
            return expected in actual
    except TypeError:
        return False  # incomparable types never match (e.g. str vs int)
    return False


def evaluate(condition: Optional[dict], data: dict) -> bool:
    """True when the condition matches the process data. None = default = True."""
    if condition is None:
        return True
    if "all" in condition:
        return all(_clause(data, c) for c in condition["all"])
    if "any" in condition:
        return any(_clause(data, c) for c in condition["any"])
    return _clause(data, condition)  # bare single clause


def condition_fields(condition: Optional[dict]) -> set[str]:
    """Every field a condition reads — for validation against data_fields."""
    if condition is None:
        return set()
    clauses = condition.get("all") or condition.get("any")
    if clauses is None:
        clauses = [condition]
    return {c["field"] for c in clauses if isinstance(c, dict) and "field" in c}


def check_condition_shape(condition: Optional[dict]) -> list[str]:
    """Structural problems with a condition dict (empty list = well-formed)."""
    if condition is None:
        return []
    problems: list[str] = []
    if not isinstance(condition, dict):
        return ["condition must be a dict"]
    if "all" in condition or "any" in condition:
        group_key = "all" if "all" in condition else "any"
        clauses = condition.get(group_key)
        if not isinstance(clauses, list) or not clauses:
            return [f"'{group_key}' must be a non-empty list of clauses"]
    else:
        clauses = [condition]
    for clause in clauses:
        if not isinstance(clause, dict):
            problems.append("clause must be a dict")
            continue
        if not clause.get("field") or not isinstance(clause.get("field"), str):
            problems.append("clause missing string 'field'")
        op = clause.get("op")
        if op not in OPS:
            problems.append(f"clause op {op!r} not one of {OPS}")
    return problems
