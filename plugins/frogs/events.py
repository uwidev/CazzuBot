"""Frog domain events — emitted after the transactional work completes.

Consumers (e.g. a future badge system) subscribe via ``bot.events.on``;
they observe captures/consumes without the frogs flow knowing them. Plain
value payloads only — the bus stays framework-agnostic. The species key
travels as a :class:`SpeciesKey` member, never a string, so consumers
compare against typed keys.

Call graph (per the self-documenting rule): each event below is emitted by
exactly one place in the frogs flow — see the docstring on each event —
and observed by whatever subscribes via ``bot.events.on(EventType, ...)``
(nothing yet; the badge system is the planned first consumer). ``emit``
awaits every matching handler in registration order and swallows failures,
so observers can never break the capture/consume.
"""

from __future__ import annotations

from dataclasses import dataclass

from cazzubot.models import FrogState, FrogItemKey


@dataclass(frozen=True, slots=True)
class FrogCapturedEvent:
    """A capture completed: log written, catch behavior ran.

    An item is granted only when the species' catch behavior does it
    (``grant_catch``); a Cluster capture runs its burst and grants nothing.
    Sole emitter: ``plugins/frogs/factory.py`` ``FrogCatchMenu.catch``,
    right after the capture transaction (post-behavior, post-message).
    """

    uid: int
    species_key: FrogItemKey
    at: str  # ISO-8601 UTC


@dataclass(frozen=True, slots=True)
class FrogConsumedEvent:
    """A consume completed: exp + statuses applied, inventory decremented.

    Sole emitter: ``plugins/frogs/items.py`` ``_consume_item``, right after
    the item-owned consume (post-statuses, post-exp).
    """

    uid: int
    species_key: FrogItemKey
    amount: int
    state: FrogState
    at: str  # ISO-8601 UTC
