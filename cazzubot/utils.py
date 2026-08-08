"""General-purpose helpers shared by plugins."""

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any, NamedTuple, TypeVar, cast

import hikari
import lightbulb
import pendulum

from cazzubot.bot import CazzuBot
from cazzubot.models import MemberSnapshot

_log = logging.getLogger(__name__)

T = TypeVar("T")


class OldNew(NamedTuple):
    """Pair of (old, new) values, e.g. level or rank before/after a message."""

    old: Any
    new: Any


def month2season(month: int) -> int:
    """Bucket a calendar month (1-12) into a season (0-3).

    Matches v1: months are zero-indexed then floordiv 3, so
    Jan-Mar -> 0, Apr-Jun -> 1, Jul-Sep -> 2, Oct-Dec -> 3.
    """
    return (month - 1) // 3


def season_start(year: int, season: int) -> pendulum.DateTime:
    """First instant of a season (Jan/Apr/Jul/Oct 1st, UTC)."""
    if not 0 <= season <= 3:
        raise ValueError("Seasons must be in the range of 0-3")
    return pendulum.datetime(year, 1 + 3 * season, 1, tz="UTC")


def season_end(year: int, season: int) -> pendulum.DateTime:
    """First instant after a season (exclusive upper bound)."""
    return season_start(year, season).add(months=3)


def ordinal(n: int) -> str:
    """1st, 2nd, 3rd, 4th, …"""
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def calc_percentile(rank: int, total: int) -> float:
    """Percentile of a rank within a total (1 is best)."""
    return (total - rank + 1) / total * 100 if total else 0.0


def prepare_embed(
    title: str | None = None,
    description: str | None = None,
    *,
    color: int = 0x9EDBF7,
) -> hikari.Embed:
    """Standard embed with the -sarono footer."""
    embed = hikari.Embed(title=title, description=description, color=color)
    embed.set_footer(
        text="-sarono",
        icon="https://files.catbox.moe/3cy0by.webp",
    )
    return embed


def member_snapshot(
    member: hikari.Member | hikari.User,
) -> MemberSnapshot:
    """Plain values for template formatting (no hikari objects)."""
    display_name = member.display_name
    if not isinstance(display_name, str):
        # partial User without global_name/username — rare cache edge
        display_name = ""
    return MemberSnapshot(
        id=member.id,
        display_name=display_name,
        mention=member.mention,
        avatar_url=str(member.display_avatar_url),
    )


async def find_user(
    bot: CazzuBot, _ctx: Any, uid: int
) -> hikari.User | hikari.Member | None:
    """Resolve a user id from the cache or a REST fetch."""
    guild = bot.guild
    if guild is not None:
        member = bot.cache.get_member(guild.id, uid)
        if member:
            return member
    user = bot.cache.get_user(uid)
    if user:
        return user
    try:
        return await bot.rest.fetch_user(uid)
    except hikari.NotFoundError:
        return None


def schedule_delete(
    bot: CazzuBot,
    channel_id: int,
    message_id: int,
    delay: float,
) -> None:
    """Delete a message after a delay (fire-and-forget).

    Replaces discord.py's ``delete_after`` kwarg, which hikari doesn't have.
    """

    async def _delete() -> None:
        await asyncio.sleep(delay)
        try:
            await bot.rest.delete_message(channel_id, message_id)
        except hikari.NotFoundError:
            pass

    asyncio.create_task(_delete())


_EMOJI_TAG = re.compile(r"<a?:[a-zA-Z0-9_]+:(\d{15,25})>")


def button_emoji(emoji: str) -> str | int:
    """A custom-emoji tag ``<:name:id>`` -> its id for component payloads.

    hikari's button builders only split *ints* into ``{"id": ...}``; any
    string goes wholesale into ``emoji.name``, which Discord rejects for
    custom emojis (``Invalid emoji``). Unicode emojis pass through.
    """
    match = _EMOJI_TAG.fullmatch(emoji)
    if match:
        return int(match.group(1))
    return emoji


class ConfirmMenu(lightbulb.components.Menu):
    """Yes/No button prompt; ``value`` is True / False / None (timed out).

    Only the invoking author's clicks count. On an answer the prompt is
    deleted when ``delete_after`` is set (mirroring the old reaction-based
    flow), otherwise its buttons are stripped from it.
    """

    def __init__(
        self,
        author_id: int,
        *,
        delete_after: bool = True,
    ) -> None:
        super().__init__()
        self.author_id = author_id
        self.delete_after = delete_after
        self.value: bool | None = None
        self.add_interactive_button(
            hikari.ButtonStyle.SUCCESS, self._yes, label="Yes", emoji="👍"
        )
        self.add_interactive_button(
            hikari.ButtonStyle.DANGER, self._no, label="No", emoji="❌"
        )

    async def _finish(
        self, mctx: lightbulb.components.MenuContext, value: bool
    ) -> None:
        if mctx.interaction.user.id != self.author_id:
            await mctx.respond(
                "This prompt is not for you.",
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return
        self.value = value
        if self.delete_after:
            try:
                await mctx.delete_response(mctx.interaction.id)
            except hikari.NotFoundError:
                pass
        else:
            await mctx.edit_response(mctx.interaction.id, component=None)
        mctx.stop_interacting()

    async def _yes(self, mctx: lightbulb.components.MenuContext) -> None:
        await self._finish(mctx, True)

    async def _no(self, mctx: lightbulb.components.MenuContext) -> None:
        await self._finish(mctx, False)


async def author_confirm(
    ctx: lightbulb.Context,
    confirmation_msg: str = "Please confirm.",
    *,
    delete_after: bool = True,
) -> bool:
    """Ask the author to confirm with Yes/No buttons; True if Yes."""
    member = ctx.member or ctx.user
    menu = ConfirmMenu(member.id, delete_after=delete_after)
    await ctx.respond(
        confirmation_msg,
        # the menu is a sequence of row builders (no public build())
        components=cast(Any, menu),
    )
    try:
        await menu.attach(ctx.client, timeout=7.0)
    except asyncio.TimeoutError:
        # timed out — mirror old behaviour: remove prompt
        try:
            await ctx.delete_response(ctx.interaction.id)
        except hikari.NotFoundError:
            pass
        return False
    return bool(menu.value)


def deep_map(
    value: Any, formatter: Callable[..., str], **kwargs: Any
) -> Any:
    """In-place walk over dicts/lists applying ``formatter`` to every string."""
    if isinstance(value, dict):
        mapping = cast(dict[Any, Any], value)
        for k, v in mapping.items():
            mapping[k] = deep_map(v, formatter, **kwargs)
        return mapping
    if isinstance(value, list):
        items = cast(list[Any], value)
        for i, v in enumerate(items):
            items[i] = deep_map(v, formatter, **kwargs)
        return items
    if isinstance(value, str):
        return formatter(value, **kwargs)
    return value


def split_duration_and_text(raw: str) -> tuple[str, str]:
    """Split a leading time token from the rest of a string.

    Used by ``mute``/``ban``: "2h because i said so" -> ("2h", "because…").
    Returns ``(raw, "")`` when no leading duration parses.
    """
    from cazzubot.timeparse import InvalidTimeError, parse_duration

    first = raw.split(maxsplit=1)
    try:
        parse_duration(first[0])
    except InvalidTimeError, ValueError, IndexError:
        return raw, ""
    return first[0], first[1] if len(first) > 1 else ""
