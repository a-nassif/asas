# asas-validation

Declarative temporal/cross-field validation: the host declares a catalog of `Rule`s
(`not_future` / `not_past` / `order` / `max_age`) in its own code, registers its entities'
field names, and hooks `raise_if_invalid` into create/update routers. Violations come back
as FastAPI-native 422 envelopes; `build_router()` serves the rule set (ETag-cached) so
clients can mirror the same constraints.

Table-less variant of the Asas host contract: no session dependency, no `seed`, no
`migrate`. See the repo README for the full contract.
