"""Declarative validation rules — pure data, declared by the host.

A ``Rule`` is an entity, a constraint ``kind``, the field(s) it reads, and a human
message. The host declares its whole catalog once at boot via :func:`declare_rules`
(rules are developer invariants, not admin-tunable data — they live in the host's
code, not in this package and not in a DB).

Kinds (implemented in ``engine._KINDS``):
  * ``not_future(field)``      — field <= today
  * ``not_past(field)``        — field >= today
  * ``order(earlier, later)``  — earlier <= later                (cross-field)
  * ``max_age(field)``         — field >= today - ``params["years"]`` years

Extra parameters (e.g. ``years`` for ``max_age``) go in ``params``. The violation
attaches to the rule's **last** own field (``Rule.target``) — the one usually being
edited to an invalid value — so the UI can flag the right input. A field spelled
``parent.field`` is **namespaced**: it reads a related record's value from the
``context`` mapping the caller passes to ``evaluate``.
"""

from dataclasses import dataclass, field
from typing import Iterable


@dataclass(frozen=True)
class Rule:
    entity: str
    kind: str
    fields: tuple[str, ...]
    message: str
    code: str
    params: dict = field(default_factory=dict)

    @property
    def target(self) -> str:
        """The field a violation attaches to (for per-field UI errors). Prefers the rule's
        own (non-namespaced) field so a cross-entity violation flags the child's input, not
        the referenced parent field."""
        own = [f for f in self.fields if "." not in f]
        return own[-1] if own else self.fields[-1]


_RULES: tuple[Rule, ...] = ()


def declare_rules(rules: Iterable[Rule]) -> None:
    """Replace the declared rule set with ``rules`` — the host calls this once at boot
    (idempotent: re-declaring the same catalog is a no-op in effect). Follow with
    :func:`asas_validation.assert_rules_known` after registering known fields."""
    global _RULES
    _RULES = tuple(rules)


def declared_rules() -> tuple[Rule, ...]:
    return _RULES


def rules_for(entity: str) -> list[Rule]:
    return [r for r in _RULES if r.entity == entity]
