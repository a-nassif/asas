"""In-process event seam — decisions resume flows via events, never live waits
(Power Automate lesson). The notifications module (epic WXL-209) subscribes here;
until it lands, events simply have no subscribers.

Delivery is BEST-EFFORT and non-blocking (house graceful-degradation rule): a
subscriber exception is swallowed — a notification failure must never fail an
engine transition.

Event kinds emitted by the engine:
    process.opened, process.completed, process.canceled, process.error,
    node.activated, approval.activated, info.requested, info.answered
Payloads are small dicts of ids/keys — subscribers reload what they need. Events
consumed by the notifications bridge additionally carry the producing ``session``
and fire INSIDE the transaction, so subscriber inserts commit atomically with the
domain change (transactional outbox); process.canceled stays post-commit — its
subscriber (teamjoin) deliberately reloads committed state in its own session.
"""

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

Subscriber = Callable[[str, dict], Any]

_SUBSCRIBERS: list[Subscriber] = []


def subscribe(fn: Subscriber) -> None:
    """Register a subscriber called as fn(kind, payload) for every event."""
    _SUBSCRIBERS.append(fn)


def emit(kind: str, payload: dict) -> None:
    for fn in _SUBSCRIBERS:
        try:
            fn(kind, payload)
        except Exception:  # noqa: BLE001 - best-effort by design
            logger.exception("workflow event subscriber failed for %s", kind)


def clear_subscribers() -> None:
    """Test helper."""
    _SUBSCRIBERS.clear()
