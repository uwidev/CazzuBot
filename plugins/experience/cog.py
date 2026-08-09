"""Experience plugin extension — message exp pipeline, membership card,
leaderboards."""

import asyncio
from math import trunc
from typing import Any, cast

import hikari
import lightbulb
import pendulum

from cazzubot import leaderboard, levels, utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.utils import INITIAL_RESPONSE_IDENTIFIER
from lightbulb.prefab import checks as prefab_checks

from cazzubot.window import command_window, window_success, window_warn

from . import db as exp_db
from .logic import award_exp

# -- experience rates live in ``plugins/experience/logic.py`` --------------

loader = lightbulb.Loader()

_SCOREBOARD_STAMP = (
    "https://cdn.discordapp.com/emojis/695126165756837999.webp"
    "?size=160&quality=lossless"
)
_COLOR = hikari.Color.from_hex_code("#a2dcf7")

exp = lightbulb.Group(
    "exp", "Experience, the membership card and leaderboards."
)

_OWNER = prefab_checks.owner_only
_ADMIN = prefab_checks.has_permissions(hikari.Permissions.ADMINISTRATOR)

# serialize exp updates per user so concurrent messages can't race the
# msg_cnt/lifetime read-modify-write (single process, so module state is fine)
_exp_locks: dict[int, asyncio.Lock] = {}


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


def _found_name(user: hikari.User | hikari.Member | None, uid: int) -> str:
    """A user's display name, or the raw id when unknown/partial."""
    if user is None:
        return str(uid)
    name = user.display_name
    return name if isinstance(name, str) else str(uid)


# -- message exp pipeline --------------------------------------------------


@loader.listener(hikari.MessageCreateEvent)
async def on_message(event: hikari.MessageCreateEvent) -> None:
    """Award exp based on daily message count; handle level/rank ups."""
    bot = cast(CazzuBot, event.app)
    if not event.is_human:
        return
    message = event.message
    if message.guild_id != bot.config.guild_id:
        return

    lock = _exp_locks.setdefault(message.author.id, asyncio.Lock())
    async with lock:
        await _award_exp(bot, message)


async def _award_exp(bot: CazzuBot, message: hikari.Message) -> None:
    """Controller: resolve, call the service, present the outcome."""
    now = pendulum.now("UTC")
    uid = message.author.id
    result = await award_exp(bot.db, uid=uid, now=now)
    if result is None:
        return  # cooldown active or row missing

    # presentation — level-up/rank-up notifications (cross-plugin)
    from plugins.levels.presenter import present_level_up
    from plugins.ranks.presenter import present_ranks

    await present_level_up(
        bot, message, result.seasonal_level, delete_after=7
    )
    await present_ranks(
        bot,
        message.member or message.author,
        message.channel_id,
        result.seasonal_level,
        result.lifetime_level,
        delete_after=7,
    )


# -- commands --------------------------------------------------------------


@exp.register
class Card(
    lightbulb.SlashCommand,
    name="card",
    description="Show this season's experience and membership card.",
):
    user = lightbulb.user("user", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        target = self.user or ctx.member or ctx.user
        now = pendulum.now("UTC")
        rows = await exp_db.seasonal_ranked(
            bot.db, now.year, (now.month - 1) // 3
        )
        await ctx.respond(
            embed=await _prepare_personal_summary(bot, ctx, target, rows)
        )


@exp.register
class Lifetime(
    lightbulb.SlashCommand,
    name="lifetime",
    description="Lifetime experience variant of the membership card.",
):
    user = lightbulb.user("user", "The member to show", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        target = self.user or ctx.member or ctx.user
        rows = await exp_db.lifetime_ranked(bot.db)
        await ctx.respond(
            embed=await _prepare_personal_summary(
                bot, ctx, target, rows, lifetime=True
            )
        )


@exp.register
class Top(
    lightbulb.SlashCommand,
    name="top",
    description="Display the seasonal experience leaderboard (button-paged).",
):
    year = lightbulb.integer(
        "year", "The year", default=None, min_value=2023
    )
    season = lightbulb.integer(
        "season",
        "The season (1-4)",
        default=None,
        min_value=1,
        max_value=4,
    )
    page = lightbulb.integer("page", "The page", default=None, min_value=1)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        now = pendulum.now("UTC")
        year = self.year or now.year
        season = self.season or (now.month - 1) // 3 + 1
        page = self.page or 1

        if not 1 <= season <= 4:
            raise UserInputError(
                f"Season {season} is not a valid number (1-4)"
            )
        if not 2023 <= year <= now.year:
            raise UserInputError(
                f"Year {year} is not a valid year, or is too early."
            )
        if page <= 0:
            raise UserInputError(f"Page {page} must be greater than 0.")

        date = pendulum.datetime(year, ((season - 1) * 3) + 1, 1)
        rows = await exp_db.seasonal_ranked(
            bot.db, date.year, (date.month - 1) // 3
        )

        menu = TopMenu(bot, ctx, date, rows, page=page)
        await ctx.respond(
            embed=await _top_embed(ctx, date, rows, page),
            # the menu is a sequence of row builders (no public build())
            components=cast(Any, menu),
        )
        try:
            await menu.attach(ctx.client, timeout=30)
        except asyncio.TimeoutError:
            await ctx.edit_response(
                INITIAL_RESPONSE_IDENTIFIER, component=None
            )


@exp.register
class Resync(
    lightbulb.SlashCommand,
    name="resync",
    description="Rebuild every member's lifetime exp from the exp logs.",
    hooks=[_OWNER],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        if not await utils.author_confirm(ctx):
            return
        async with command_window(ctx) as window:
            window.info("Fetching exp logs...")
            await window.flush()  # ack early before the big UPDATE
            await exp_db.sync_with_exp_logs(bot.db)
            window.success("Lifetime exp synced.")


exp_quiet = exp.subgroup(
    "quiet", "Channels where level-up messages are suppressed."
)


@exp_quiet.register
class Quiet(
    lightbulb.SlashCommand,
    name="list",
    description="List channels where level-up messages are suppressed.",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        quiets: list[int] = await bot.settings.get("level.quiet", []) or []
        await ctx.respond(str(quiets))


@exp_quiet.register
class QuietAdd(
    lightbulb.SlashCommand,
    name="add",
    description="Suppress level-up messages in a channel.",
    hooks=[_ADMIN],
):
    channel = lightbulb.channel(
        "channel",
        "The channel to quiet",
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        quiets: list[int] = await bot.settings.get("level.quiet", []) or []
        if self.channel.id in quiets:
            await window_warn(ctx, "Channel already in the quiet list")
            return
        quiets.append(self.channel.id)
        await bot.settings.set("level.quiet", quiets)
        await window_success(
            ctx, f"Added {self.channel.mention} to the quiet list"
        )


@exp_quiet.register
class QuietDel(
    lightbulb.SlashCommand,
    name="del",
    description="Un-suppress level-up messages in a channel.",
    hooks=[_ADMIN],
):
    channel = lightbulb.channel(
        "channel",
        "The channel to un-quiet",
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        quiets: list[int] = await bot.settings.get("level.quiet", []) or []
        if self.channel.id not in quiets:
            await window_warn(ctx, "Channel was never in the quiet list")
            return
        quiets.remove(self.channel.id)
        await bot.settings.set("level.quiet", quiets)
        await window_success(
            ctx, f"Removed {self.channel.mention} from the quiet list"
        )


loader.command(exp)


# -- membership card / leaderboard embeds ----------------------------------


async def _prepare_personal_summary(
    bot: CazzuBot,
    ctx: lightbulb.Context,
    user: hikari.User | hikari.Member,
    rows: list[tuple[int, int, int]],
    *,
    lifetime: bool = False,
) -> hikari.Embed:
    """The "Club Membership Card" embed."""
    uid = user.id
    uids = [r[1] for r in rows]
    if uid not in uids:
        embed = hikari.Embed(
            description=f"{user.display_name} has no experience yet.",
            color=_COLOR,
        )
        embed.set_author(
            name=f"{user.display_name}'s Club Membership Card",
            icon=_SCOREBOARD_STAMP,
        )
        embed.set_thumbnail(str(user.display_avatar_url))
        return embed

    uid_index = uids.index(uid)
    subset, subset_i = leaderboard.create_focus_subset(rows, uid_index)

    ranks = [r[0] for r in subset]
    exps = [r[2] for r in subset]
    lvls = [levels.level_from_exp(e) for e in exps]
    names: list[str] = []
    for uid_ in [r[1] for r in subset]:
        found = await utils.find_user(bot, ctx, uid_)
        names.append(_found_name(found, uid_))

    window = list(zip(ranks, exps, lvls, names))
    headers = ["Rank", "Exp", "Lv", "User"]
    align = ["<", ">", ">", ">"]
    max_padding = [0, 0, 0, 16]

    scoreboard = leaderboard.format(
        window, headers, align=align, max_padding=max_padding
    )
    col_widths = leaderboard.calc_max_col_width(
        window, headers, max_padding
    )
    leaderboard.highlight_row(scoreboard, subset_i, col_widths)
    scoreboard_s = "\n".join(scoreboard)

    # member stats
    from cazzubot.models import WindowEnum
    from plugins.ranks.db import of_member

    rid = await of_member(
        bot.db,
        uid,
        mode=WindowEnum.LIFETIME if lifetime else WindowEnum.SEASONAL,
    )
    role = None
    guild = bot.guild
    if rid is not None and guild is not None:
        role = bot.cache.get_role(rid)

    lvl = lvls[subset_i]
    exp = exps[subset_i]
    rank = ranks[subset_i]

    if lifetime:
        total = await exp_db.total_members(bot.db)
    else:
        now = pendulum.now("UTC")
        total = await exp_db.seasonal_total_members(
            bot.db, now.year, (now.month - 1) // 3
        )

    percentile = utils.calc_percentile(rank, total)

    embed = hikari.Embed(color=_COLOR)
    embed.set_author(
        name=f"{user.display_name}'s Club Membership Card",
        icon=_SCOREBOARD_STAMP,
    )
    embed.set_thumbnail(str(user.display_avatar_url))
    embed.description = f"""
		Rank: {role.mention if role else "`None`"}
		Level: **`{lvl:,}`**
		Experience: **`{exp:,}`**

		You are currently the `{utils.ordinal(trunc(percentile))}` percentile of all members!
		```py\n{scoreboard_s}```"""
    return embed


async def _top_embed(
    ctx: lightbulb.Context,
    date: pendulum.DateTime,
    rows: list[tuple[int, int, int]],
    page: int,
) -> hikari.Embed:
    """The leaderboard pager embed (pageable via TopMenu)."""
    bot = _bot(ctx)
    embed = hikari.Embed(color=_COLOR)
    embed.set_author(
        name="Club Cirno Leaderboards", icon=_SCOREBOARD_STAMP
    )

    if not rows:
        scoreboard_s = "No data has been logged during this time period."
    else:
        if rows and rows[0]:
            top_user = await utils.find_user(bot, ctx, rows[0][1])
            if top_user:
                embed.set_thumbnail(str(top_user.display_avatar_url))

        subset = rows[(page - 1) * 10 : page * 10]
        ranks = [r[0] for r in subset]
        uids = [r[1] for r in subset]
        exps = [r[2] for r in subset]
        lvls = [levels.level_from_exp(e) for e in exps]
        names: list[str] = []
        for id_ in uids:
            user = await utils.find_user(bot, ctx, id_)
            names.append(_found_name(user, id_))

        window = list(zip(ranks, exps, lvls, names))
        headers = ["Rank", "Exp", "Lv", "User"]
        align = ["<", ">", ">", ">"]
        max_padding = [0, 0, 0, 16]
        scoreboard = leaderboard.format(
            window, headers, align=align, max_padding=max_padding
        )
        author_id = (ctx.member or ctx.user).id
        if author_id in uids:
            col_widths = leaderboard.calc_max_col_width(
                window, headers, max_padding
            )
            leaderboard.highlight_row(
                scoreboard, uids.index(author_id), col_widths
            )
        scoreboard_s = "\n".join(scoreboard)

    embed.description = f"""
		Year: **`{date.year}`**
		Season: **`{(date.month - 1) // 3 + 1}`**
		Page: **`{page}`**
		```py\n{scoreboard_s}```"""
    return embed


class TopMenu(lightbulb.components.Menu):
    """Seasonal leaderboard pager: page ◀/▶ and season ⬅/➡ buttons."""

    def __init__(
        self,
        bot: CazzuBot,
        ctx: lightbulb.Context,
        date: pendulum.DateTime,
        rows: list[tuple[int, int, int]],
        page: int = 1,
    ) -> None:
        super().__init__()
        self.bot = bot
        self.ctx = ctx
        self.author_id = (ctx.member or ctx.user).id
        self.date = date
        self.rows = rows
        self.page = page
        self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self._prev_season, emoji="⬅"
        )
        self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self._prev_page, emoji="◀"
        )
        self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self._next_page, emoji="▶"
        )
        self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self._next_season, emoji="➡"
        )

    async def _edit(self, mctx: lightbulb.components.MenuContext) -> None:
        embed = await _top_embed(self.ctx, self.date, self.rows, self.page)
        # respond(edit=True) is the atomic ack+edit: lightbulb menu clicks
        # arrive un-acked, and edit_response on the un-acked interaction 404s
        await mctx.respond(edit=True, embed=embed)

    async def _deny(self, mctx: lightbulb.components.MenuContext) -> None:
        await mctx.respond(
            "This leaderboard is not yours to page.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def _prev_season(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        if mctx.interaction.user.id != self.author_id:
            await self._deny(mctx)
            return
        self.date = self.date.subtract(months=3)
        self.rows = await exp_db.seasonal_ranked(
            self.bot.db, self.date.year, (self.date.month - 1) // 3
        )
        self.page = 1
        await self._edit(mctx)

    async def _prev_page(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        if mctx.interaction.user.id != self.author_id:
            await self._deny(mctx)
            return
        self.page = max(self.page - 1, 1)
        await self._edit(mctx)

    async def _next_page(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        if mctx.interaction.user.id != self.author_id:
            await self._deny(mctx)
            return
        self.page = min(self.page + 1, max(len(self.rows) // 10, 1))
        await self._edit(mctx)

    async def _next_season(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        if mctx.interaction.user.id != self.author_id:
            await self._deny(mctx)
            return
        self.date = self.date.add(months=3)
        self.rows = await exp_db.seasonal_ranked(
            self.bot.db, self.date.year, (self.date.month - 1) // 3
        )
        self.page = 1
        await self._edit(mctx)
