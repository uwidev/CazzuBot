"""General-purpose helpers shared by plugins."""

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Any, NamedTuple, TypeVar, cast

import hikari
import lightbulb
import pendulum
from lightbulb.prefab import checks as prefab_checks

from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.models import MemberSnapshot

# lightbulb's sentinel for "the initial interaction response" (context.py
# compares response ids against it before choosing edit_initial_response vs
# edit_message). Response ids returned by ``respond()`` are this sentinel
# when the call created the initial response — NOT the message id.
from lightbulb.internal import constants as _lb_constants

INITIAL_RESPONSE_IDENTIFIER = _lb_constants.INITIAL_RESPONSE_IDENTIFIER

_log = logging.getLogger(__name__)

T = TypeVar("T")


def bot_from(ctx: lightbulb.Context) -> CazzuBot:
    """The ``CazzuBot`` behind a lightbulb context (``ctx.client.app``)."""
    return cast(CazzuBot, ctx.client.app)


# the shared permission hooks — one source for the ADMINISTRATOR constant
OWNER_ONLY = prefab_checks.owner_only
ADMIN_ONLY = prefab_checks.has_permissions(
    hikari.Permissions.ADMINISTRATOR
)


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


def season_bounds(year: int, season: int) -> tuple[str, str]:
    """ISO-8601 (start, end) pair of a season (0-3), UTC."""
    start = season_start(year, season)
    return start.isoformat(), season_end(year, season).isoformat()


_WEEK_STARTS = ("sunday", "monday")


def week_start(
    now: pendulum.DateTime, *, start: str = "sunday"
) -> pendulum.DateTime:
    """00:00 UTC of the week containing ``now`` (start: 'sunday'|'monday').

    Pendulum weeks run Monday→Sunday, so ``start_of("week")`` lands on the
    Monday *before* a Sunday ``now`` — for Sunday-start weeks, step back a
    day, and for Sundays the week starts on the day itself.
    """
    if start not in _WEEK_STARTS:
        raise UserInputError(f"week start must be one of {_WEEK_STARTS}")
    if start == "monday":
        return now.start_of("week")
    if now.day_of_week == pendulum.SUNDAY:
        return now.start_of("day")
    return now.start_of("week").subtract(days=1)


def week_start_of(
    year: int, week: int, *, start: str = "sunday"
) -> pendulum.DateTime:
    """00:00 UTC of the first day of ``week`` of ``year``.

    Week numbers follow ISO 8601; for Sunday-start weeks the week starts on
    the Sunday that ends the ISO week (so ``week_start(now)`` and
    ``week_start_of`` round-trip). Raises ``UserInputError`` for weeks that
    don't exist in ``year``.
    """
    if not 1 <= week <= 53:
        raise UserInputError(f"week must be between 1 and 53, got {week}")
    try:
        parsed = pendulum.parse(f"{year}-W{week:02}")
    except ValueError as err:  # ParserError for nonexistent ISO weeks
        raise UserInputError(
            f"week {week} does not exist in {year}"
        ) from err
    if not isinstance(parsed, pendulum.DateTime):
        raise UserInputError(f"week {week} does not exist in {year}")
    monday = parsed
    if monday.isocalendar()[1] != week:
        raise UserInputError(f"week {week} does not exist in {year}")
    if start == "monday":
        return monday
    return monday.add(days=6).start_of("day")


def week_number(
    now: pendulum.DateTime, *, start: str = "sunday"
) -> tuple[int, int]:
    """(week number, week year) of the week containing ``now``.

    For Monday-start weeks this is the ISO week; for Sunday-start weeks the
    week is numbered by the ISO week of its Sunday, so it round-trips with
    ``week_start_of``.
    """
    iso = week_start(now, start=start).isocalendar()
    return iso[1], iso[0]


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
    bot: CazzuBot, uid: int
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


def found_name(user: hikari.User | hikari.Member | None, uid: int) -> str:
    """A user's display name, or the raw id when unknown/partial."""
    if user is None:
        return str(uid)
    name = user.display_name
    return name if isinstance(name, str) else str(uid)


def rank_rows(
    rows: list[dict[str, Any]], key: str
) -> list[tuple[int, int, int]]:
    """Attach RANK()-style ranks (ties share, then skip) to (uid, key) rows."""
    out: list[tuple[int, int, int]] = []
    prev: Any = None
    rank = 0
    for i, row in enumerate(rows, start=1):
        if row[key] != prev:
            rank = i
        out.append((rank, row["uid"], row[key]))
        prev = row[key]
    return out


def text_channel(
    bot: CazzuBot, channel_id: int | None
) -> hikari.TextableGuildChannel | None:
    """The cached guild channel, when it exists and can send messages."""
    if channel_id is None:
        return None
    channel = bot.cache.get_guild_channel(channel_id)
    if channel is not None and hasattr(channel, "send"):
        return cast(Any, channel)
    return None


def in_guild(bot: CazzuBot, guild_id: int | None) -> bool:
    """True when an event's guild is the one this bot serves.

    The gateway delivers events from every guild the token belongs to,
    but the bot serves one guild (``config.guild_id``) — a development
    run must ignore the production guild's events and vice versa
    (welcomes, exp, persistent buttons, …).
    """
    return guild_id == bot.config.guild_id


def channel_in_guild(bot: CazzuBot, channel_id: int) -> bool:
    """True when the cached channel belongs to the configured guild.

    For scheduler payloads that target a channel by id (frog spawns,
    counter expiry): a row armed while the bot served the other guild
    must not fire into it under the current guild mode.
    """
    channel = bot.cache.get_guild_channel(channel_id)
    return channel is not None and channel.guild_id == bot.config.guild_id


def format_member(s: str, member: MemberSnapshot, **extra: Any) -> str:
    """Format a template with the shared member placeholders + extras.

    Every feature's template formatter starts from the same member base
    (``{avatar} {name} {mention} {id}``); feature-specific placeholders
    ride along as extra keyword fields.
    """
    return s.format(
        avatar=member.avatar_url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
        **extra,
    )


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
        """Build the Yes/No buttons keyed to the invoking ``author_id``."""
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
        """Record the answer, enforce the author, and clean up the prompt."""
        if mctx.interaction.user.id != self.author_id:
            await mctx.respond(
                "This prompt is not for you.",
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return
        self.value = value
        # lightbulb does NOT ack menu clicks before calling the callback, so
        # the first response here must be a real interaction response — an
        # edit/delete via the webhook on an un-acked interaction 404s
        # (10015 Unknown Webhook) and the click dies with "did not respond".
        await mctx.defer(edit=True)  # invisible ack of the click
        if self.delete_after:
            try:
                await mctx.delete_response(INITIAL_RESPONSE_IDENTIFIER)
            except hikari.NotFoundError:
                pass
        else:
            try:
                # strip the buttons from the prompt message
                await mctx.edit_response(
                    INITIAL_RESPONSE_IDENTIFIER, component=None
                )
            except hikari.NotFoundError:
                pass
        mctx.stop_interacting()

    async def _yes(self, mctx: lightbulb.components.MenuContext) -> None:
        """Author clicked Yes → finish with ``True``."""
        await self._finish(mctx, True)

    async def _no(self, mctx: lightbulb.components.MenuContext) -> None:
        """Author clicked No → finish with ``False``."""
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
            await ctx.delete_response(INITIAL_RESPONSE_IDENTIFIER)
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
