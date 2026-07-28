"""Known-field registry. Owning modules register the set of valid field names per
entity type so policy config (and seeds) can be validated — a typo'd field name fails
loud at seed time instead of silently never matching."""

_FIELDS: dict[str, set[str]] = {}


def register_fields(entity_type: str, fields) -> None:
    """Register (or extend) the set of known field names for ``entity_type``."""
    _FIELDS.setdefault(entity_type, set()).update(fields)


def known_fields(entity_type: str) -> set[str]:
    return set(_FIELDS.get(entity_type, set()))


def registered_entities() -> list[str]:
    return sorted(_FIELDS)


def is_known(entity_type: str, field: str) -> bool:
    """True if ``field`` is registered for ``entity_type``. Unknown *entity types* are
    treated as known (not yet registered) so validation only fires once a module opts in."""
    fields = _FIELDS.get(entity_type)
    return fields is None or field in fields
