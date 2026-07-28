"""Asas validation — declarative temporal/cross-field constraint engine.

Config-as-data input validation: the host declares its rule catalog (pure data, in host
code) and this package evaluates it on every create/update, returning FastAPI-native
422 envelopes so semantic errors and body-shape errors share one client code path.
Extracted from Teamy (epic TEAMY-466; design record 0007 for the rule model, 0017 for
the extraction).

Public surface — the Asas host contract (table-less variant: no session dependency,
no ``seed``, no ``migrate``):

- :func:`declare_rules` — the host declares its whole ``Rule`` catalog once at boot.
- :func:`register_fields` — the host registers each entity's real field names, then
  calls :func:`assert_rules_known` to fail loud on a typo'd rule.
- :func:`raise_if_invalid` — router hook: evaluate an edit, raise 422 on violations.
- :func:`evaluate` / :class:`Violation` / :func:`to_http` — the pieces, for callers
  that need them separately.
- :func:`build_router` — the ``/validation/rules`` read endpoint (ETag-cached); the
  host applies auth guards when including it.
"""

from .catalog import is_known, known_fields, register_fields
from .engine import Violation, assert_rules_known, evaluate
from .errors import raise_if_invalid, to_http
from .router import build_router
from .rules import Rule, declare_rules, declared_rules, rules_for

__version__ = "0.7.0"

__all__ = [
    "Rule",
    "Violation",
    "assert_rules_known",
    "build_router",
    "declare_rules",
    "declared_rules",
    "evaluate",
    "is_known",
    "known_fields",
    "raise_if_invalid",
    "register_fields",
    "rules_for",
    "to_http",
    "__version__",
]
