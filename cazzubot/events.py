"""A tiny typed domain event bus.

Plugins emit domain events **after their transactional work completes**
(capture, consume, level-up, ...); other plugins subscribe to observe
them. Subscribers are awaited in registration order and their failures
are isolated — an observer (e.g. a future badge system) can never break
the operation that emitted the event.

This is the observation seam between plugins. Entity-bound behavior (a
species' effects) stays inline with the flow that owns the entity — it is
transactional and ordered, so it does not ride the bus.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

_log = logging.getLogger(__name__)

T = TypeVar("T")

EventHandler = Callable[[T], Awaitable[None]]


class EventBus:
    """Registers typed event handlers and dispatches emitted events."""

    def __init__(self) -> None:
        self._handlers: list[tuple[type[Any], EventHandler[Any]]] = []

    def on(self, event_type: type[T], handler: EventHandler[T]) -> None:
        """Subscribe ``handler`` to events of ``event_type`` (or a subtype).

        Called by *observers* (e.g. a badge plugin) during load to register
        interest; the emitting flow never registers handlers — it only
        calls :meth:`emit`. ``emit`` is what invokes this handler.
        """
        self._handlers.append((event_type, handler))
        _log.info("event handler registered for %s", event_type.__name__)

    async def emit(self, event: object) -> None:
        """Await every matching handler, in registration order.

        Called by the producing flow (e.g. ``FrogCatchMenu.catch`` /
        ``Consume.invoke``) **after** its transactional work — this is the
        only place handlers are invoked. A handler failure is logged and
        swallowed — observers are isolated from the emitter by contract.
        """
        for event_type, handler in self._handlers:
            if isinstance(event, event_type):
                try:
                    await handler(event)
                except Exception:
                    _log.exception(
                        "event handler for %s failed", event_type.__name__
                    )
