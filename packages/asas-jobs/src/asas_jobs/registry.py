"""Handler registry + the tenant-context seam.

A handler is ``(session, payload) -> None``; raising ⇒ the attempt fails and the
queue retries with backoff. **Every handler must be idempotent** — delivery is
at-least-once (a worker can die after the work but before the success mark).

The context binder keeps this package tenancy-agnostic: app wiring supplies a
``(session, org_id) -> None`` that binds the org's TenantContext before an
org-scoped job's handler runs (system jobs, org_id NULL, get a bare session)."""

from typing import Callable, Dict, Optional

Handler = Callable[..., None]  # (session, payload) -> None

_HANDLERS: Dict[str, Handler] = {}
_context_binder: Optional[Callable[..., None]] = None


def register_handler(kind: str, fn: Handler) -> None:
    """Idempotent by kind (mirrors chat's ``register_tool``): re-registering
    replaces, so repeated wiring runs (tests) stay harmless."""
    _HANDLERS[kind] = fn


def get_handler(kind: str) -> Optional[Handler]:
    return _HANDLERS.get(kind)


def configure_context_binder(fn: Callable[..., None]) -> None:
    global _context_binder
    _context_binder = fn


def bind_job_context(session, org_id: Optional[int]) -> None:
    """Called by the runner before invoking a handler. No-op for system jobs or
    when wiring never configured a binder (unit tests on the bare package)."""
    if org_id is not None and _context_binder is not None:
        _context_binder(session, org_id)
