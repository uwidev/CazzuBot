"""Guild-scoped listener registration.

The gateway delivers events from every guild the token belongs to, but
the bot serves ONE guild (``config.guild_id``). Every guild-scoped
listener MUST be registered through :func:`guild_listener` — it drops
events from the other guild (and DMs) before the handler runs, so a
development-mode run can never act on the production guild.

Usage in a plugin cog::

    from cazzubot.listeners import guild_listener

    @guild_listener(loader, hikari.MessageCreateEvent)
    async def on_message(event: hikari.MessageCreateEvent) -> None:
        ...
"""

from typing import Any, Callable, TypeVar, cast

import hikari
import lightbulb

from cazzubot.bot import CazzuBot
from cazzubot.utils import in_guild

EventT = TypeVar("EventT", bound=hikari.Event)

# a listener: takes the event, returns nothing meaningful
GuildListener = Callable[[EventT], Any]


def _event_guild_id(event: Any) -> int | None:
    """The event's guild id, or None for DMs/app-level events.

    Read generically rather than via hikari's event hierarchy:
    ``MessageEvent.guild_id`` asserts non-None (it would raise on DMs),
    ``InteractionCreateEvent`` has no direct ``guild_id``, and the test
    fakes aren't hikari event instances at all — so check for the
    interaction/message objects, then fall back to a plain attribute.
    """
    interaction = getattr(event, "interaction", None)
    if interaction is not None:
        return getattr(interaction, "guild_id", None)
    message = getattr(event, "message", None)
    if message is not None:
        return getattr(message, "guild_id", None)
    return getattr(event, "guild_id", None)


def guild_listener(
    loader: lightbulb.Loader, event_type: type[EventT]
) -> Callable[[GuildListener[EventT]], GuildListener[EventT]]:
    """Register a guild-scoped listener that fires only for the configured
    guild (events from the other guild and DMs are dropped first)."""

    def decorate(fn: GuildListener[EventT]) -> GuildListener[EventT]:
        @loader.listener(event_type)
        async def gated(event: EventT) -> None:
            bot = cast(CazzuBot, event.app)
            if not in_guild(bot, _event_guild_id(event)):
                return
            await fn(event)

        return gated

    return decorate
