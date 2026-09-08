"""Board plugin — reaction exclusions (owner + mod role toggle).

The owner (or a member holding the configured mod role) keeps a message
off the board by reacting to it with the configured emoji; removing the
reaction re-includes it. Never destructive to the Discord message,
reversible, and per-occurrence (message granularity). The exclusion rows
are only consulted AT POST TIME by the shared ``drop_excluded`` filter —
after a grid is posted the owner can react on a bad image and simply
re-post (no scrape, no review), and the weekly flow stays autonomous
while mods curate during the week via reactions.

Wiring mirrors ``plugins/frogs/reactions.py``: a module-level lightbulb
``loader`` with guild-scoped listeners, registered as an extension of the
board plugin. Subscribed on the concrete ``GuildReaction*`` events (the
``Reaction*`` ABCs also cover DMs, which the board never touches).
"""

import logging
from typing import cast

import hikari
import lightbulb
import pendulum

from core.bot import CazzuBot
from core.listeners import guild_listener

from . import db

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

# settings keys (core settings store, read at event time with defaults)
EXCLUDE_EMOJI_KEY = "board.exclude.emoji"
EXCLUDE_ROLE_KEY = "board.exclude.role"
DEFAULT_EXCLUDE_EMOJI = "⛔"


@guild_listener(loader, hikari.GuildReactionAddEvent)
async def on_reaction_add(event: hikari.GuildReactionAddEvent) -> None:
    """A matching emoji + authorized user excludes the reacted message."""
    bot = cast(CazzuBot, event.app)
    if event.user_id == _self_id(bot):
        return  # never let the bot's own reactions toggle exclusions
    if not await _matches_emoji(
        bot, _emoji_name(event.emoji_name), event.emoji_id
    ):
        return
    if not await _authorized(
        bot, event.user_id, event.guild_id, event.member
    ):
        return
    await db.add_exclusion(
        bot.db,
        event.message_id,
        event.user_id,
        pendulum.now("UTC").isoformat(),
    )
    _log.info(
        "board exclusion: message %s excluded by user %s",
        event.message_id,
        event.user_id,
    )


@guild_listener(loader, hikari.GuildReactionDeleteEvent)
async def on_reaction_remove(
    event: hikari.GuildReactionDeleteEvent,
) -> None:
    """Removing the reaction re-includes the message (idempotent)."""
    bot = cast(CazzuBot, event.app)
    if event.user_id == _self_id(bot):
        return
    if not await _matches_emoji(
        bot, _emoji_name(event.emoji_name), event.emoji_id
    ):
        return
    # a remove event carries no member — roles resolve from the cache
    if not await _authorized(bot, event.user_id, event.guild_id, None):
        return
    await db.remove_exclusion(bot.db, event.message_id)
    _log.info(
        "board exclusion: message %s re-included by user %s",
        event.message_id,
        event.user_id,
    )


def _emoji_name(emoji_name: str | hikari.UnicodeEmoji | None) -> str:
    """The emoji's plain text: unicode emojis arrive as objects here."""
    if emoji_name is None:
        return ""
    name = getattr(emoji_name, "name", emoji_name)
    return str(name)


def _self_id(bot: CazzuBot) -> int | None:
    """The bot's own user id, or None when it is not resolvable."""
    try:
        me = bot.get_me()
    except Exception:
        return None
    return me.id if me is not None else None


async def _matches_emoji(
    bot: CazzuBot, emoji_name: str, emoji_id: int | None
) -> bool:
    """True when the reacted emoji is the configured exclusion emoji.

    The setting holds one emoji as text: a unicode emoji (default ⛔) by
    its character, or a custom emoji by its id / name / name:id — any of
    those spellings matches.
    """
    wanted = str(
        await bot.settings.get(EXCLUDE_EMOJI_KEY, DEFAULT_EXCLUDE_EMOJI)
        or ""
    )
    if not wanted:
        return False
    if emoji_id is None:
        return wanted == emoji_name
    return wanted in (
        str(emoji_id),
        emoji_name,
        f"{emoji_name}:{emoji_id}",
    )


async def _authorized(
    bot: CazzuBot,
    user_id: int,
    guild_id: int | None,
    member: hikari.Member | None,
) -> bool:
    """Bot owner, or a member holding ``board.exclude.role`` when set.

    The role is optional: unset → owner only. Both add and remove are
    gated the same way; a removal event carries no member, so the cache
    is consulted as a fallback.
    """
    if user_id == bot.config.owner_id:
        return True
    raw_role = await bot.settings.get(EXCLUDE_ROLE_KEY)
    if raw_role is None:
        return False
    role_id = int(raw_role)

    role_ids = _member_role_ids(member)
    if not role_ids and guild_id is not None:
        try:
            cached = bot.cache.get_member(guild_id, user_id)
        except Exception:
            cached = None  # no cache wired (offline/fakes)
        role_ids = _member_role_ids(cached)
    return role_id in role_ids


def _member_role_ids(member: object | None) -> set[int]:
    """Role ids of a member stand-in (missing/unknown → empty)."""
    if member is None:
        return set()
    roles = getattr(member, "role_ids", None)
    if roles is None:
        return set()
    return set(roles)
