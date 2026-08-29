"""A tiny typed domain event bus.

Plugins emit domain events **after their transactional work completes**
(capture, consume, level-up, ...); other plugins subscribe to observe
them. Subscribers are awaited in registration order and their failures
are isolated — an observer (e.g. a future badge system) can never break
the operation that emitted the event.

This is the observation seam between plugins. Entity-bound behavior (a
species' effects) stays inline with the flow that owns the entity — it is
transactional and ordered, so it does not ride the bus.

Subscriptions are **deferred effects** (see ``cazzubot/lifecycle.py``):
``on`` returns an unsubscribe token, so a plugin can hand it to the
lifecycle at load and withdraw its interest on unload — a deactivated
component never leaves dead handlers firing.

Depended on by: ``frogs`` (emits capture/consume events); no consumers are
subscribed yet (future badges).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

_log = logging.getLogger(__name__)

T = TypeVar("T")

EventHandler = Callable[[T], Awaitable[None]]

Unsubscribe = Callable[[], None]


class EventBus:
    """Registers typed event handlers and dispatches emitted events."""

    def __init__(self) -> None:
        """Start with no registered handlers."""
        self._handlers: list[tuple[type[Any], EventHandler[Any]]] = []

    def on(
        self, event_type: type[T], handler: EventHandler[T]
    ) -> Unsubscribe:
        """Subscribe ``handler`` to events of ``event_type`` (or a subtype).

        Called by *observers* (e.g. a badge plugin) during load to register
        interest; the emitting flow never registers handlers — it only
        calls :meth:`emit`. Returns an **unsubscribe token** — call it (or
        :meth:`off`) to withdraw the subscription; a plugin should defer
        it to the lifecycle so unload removes its handlers.
        """
        self._handlers.append((event_type, handler))
        _log.info("event handler registered for %s", event_type.__name__)
        return lambda: self.off(event_type, handler)

    def off(
        self, event_type: type[Any], handler: EventHandler[Any]
    ) -> None:
        """Withdraw a subscription (removes the matching registrations).

        The inverse of :meth:`on` — the runtime side of "a deactivated
        component's handlers must not outlive it."
        """
        before = len(self._handlers)
        self._handlers = [
            (registered_type, registered_handler)
            for registered_type, registered_handler in self._handlers
            if not (
                registered_type is event_type
                and registered_handler is handler
            )
        ]
        removed = before - len(self._handlers)
        _log.info(
            "event handler unregistered for %s (%d removed)",
            event_type.__name__,
            removed,
        )

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
