How do I… emit & listen to domain events
========================================

`bot.events` is a typed domain event bus — plugins observe each other's
work after it completes, without knowing each other. This is the cross-plugin
seam (experience → levels/ranks presenters, frog captures → a future badge
system).


1. Define an event
------------------

Plain value payloads only — the bus stays framework-agnostic. A frozen
dataclass whose fields are `MemberSnapshot` values, enum members, ints,
strings:

~~~~ python
from dataclasses import dataclass

from cazzubot.models import MemberSnapshot


@dataclass(frozen=True, slots=True)
class BadgeGrantedEvent:
    uid: int
    badge_key: str
    at: str  # ISO-8601 UTC
~~~~

See `plugins/frogs/events.py` for the house style.


2. Emit after the work completes
--------------------------------

Emit **after** your transactional write, never before — observers must see
committed state:

~~~~ python
await bot.events.emit(BadgeGrantedEvent(uid=uid, badge_key=key, at=now))
~~~~

Failures in observers are logged and swallowed, so they can never break your
operation.


3. Subscribe (an observer)
--------------------------

`on` returns an **unsubscribe token**; hand it to the lifecycle so unload
withdraws your handler (a deactivated component never leaves dead handlers):

~~~~ python
from cazzubot.events import EventBus


async def on_load(self, bot):
    token = bot.events.on(BadgeGrantedEvent, self._on_badge_granted)
    bot.lifecycle.defer(self.name, token)
~~~~

The handler receives the event object:

~~~~ python
async def _on_badge_granted(self, event: BadgeGrantedEvent) -> None: ...
~~~~


4. Rules
--------

 -  `on` / `off` both take the event *type*; handlers are awaited in
    registration order.
 -  Defer the unsubscribe token in `on_load` — never leak a subscription
    across a reload.
 -  Entity-bound behavior stays inline with the flow that owns it; the bus is
    only for observation between plugins.
