"""Experience plugin extension — message exp pipeline, membership card,
leaderboards."""

import asyncio
from typing import Any, cast
from weakref import WeakValueDictionary

import hikari
import lightbulb
import pendulum

from core import leaderboard, levels, utils
from core.bot import CazzuBot
from core.errors import UserInputError
from core.listeners import guild_listener
from core.utils import INITIAL_RESPONSE_IDENTIFIER

from core.window import command_window, window_success, window_warn

from . import db as exp_db
from .logic import award_exp

# -- experience rates live in ``plugins/experience/logic.py`` --------------

loader = lightbulb.Loader()

_SCOREBOARD_STAMP = (
    "https://cdn.discordapp.com/emojis/695126165756837999.webp"
    "?size=160&quality=lossless"
)
_COLOR = hikari.Color.from_hex_code("#a2dcf7")


def _mode_option(description: str):
    """The seasonal/lifetime window choice (card and board share it)."""
    return lightbulb.string(
        "mode",
        description,
        default="seasonal",
        choices=[
            lightbulb.Choice("Seasonal", "seasonal"),
            lightbulb.Choice("Lifetime", "lifetime"),
        ],
    )


experience = lightbulb.Group(
    "experience", "Experience, the membership card and leaderboards."
)


# serialize exp updates per user so concurrent messages can't race the
# msg_cnt/lifetime read-modify-write (single process, so module state is fine)
_exp_locks: WeakValueDictionary[int, asyncio.Lock] = WeakValueDictionary()


# -- message exp pipeline --------------------------------------------------


@guild_listener(loader, hikari.MessageCreateEvent)
async def on_message(event: hikari.MessageCreateEvent) -> None:
    """Award exp based on daily message count; handle level/rank ups."""
    bot = cast(CazzuBot, event.app)
    if not event.is_human:
        return
    message = event.message

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


@experience.register
class View(
    lightbulb.SlashCommand,
    name="view",
    description="Show a member's experience and membership card.",
):
    """Show a member's seasonal or lifetime membership card."""

    user = lightbulb.user("user", "The member to show", default=None)
    mode = _mode_option("The card window")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Render the membership card embed for the chosen window."""
        bot = utils.bot_from(ctx)
        target = self.user or ctx.member or ctx.user
        lifetime = self.mode == "lifetime"
        if lifetime:
            rows = await exp_db.lifetime_ranked(bot.db)
        else:
            now = pendulum.now("UTC")
            rows = await exp_db.seasonal_ranked(
                bot.db, now.year, utils.month2season(now.month)
            )
        await ctx.respond(
            embed=await _prepare_personal_summary(
                bot, ctx, target, rows, lifetime=lifetime
            )
        )


@experience.register
class Leaderboard(
    lightbulb.SlashCommand,
    name="leaderboard",
    description="Display the seasonal or lifetime leaderboard (paged).",
):
    """Display the seasonal or lifetime experience leaderboard."""

    mode = _mode_option("The board window")
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
        """Render the paged leaderboard and attach the pager menu."""
        bot = utils.bot_from(ctx)
        now = pendulum.now("UTC")
        page = self.page or 1
        lifetime = self.mode == "lifetime"

        if lifetime:
            # the lifetime board is a single flat window: the seasonal
            # options have nothing to select, so refuse them outright
            # rather than silently ignoring what the member typed
            if self.year is not None or self.season is not None:
                raise UserInputError(
                    "The lifetime board has no year or season."
                )
            date = None
            rows = await exp_db.lifetime_ranked(bot.db)
        else:
            year = self.year or now.year
            season = self.season or utils.month2season(now.month) + 1

            # season/page are already bounds-validated by the options;
            # only the year's upper bound is live (no max_value)
            if not 2023 <= year <= now.year:
                raise UserInputError(
                    f"Year {year} is not a valid year, or is too early."
                )

            date = pendulum.datetime(year, ((season - 1) * 3) + 1, 1)
            rows = await exp_db.seasonal_ranked(
                bot.db, date.year, utils.month2season(date.month)
            )

        menu = TopMenu(bot, ctx, date, rows, page=page, lifetime=lifetime)
        await ctx.respond(
            embed=await _top_embed(
                ctx, date, rows, page, lifetime=lifetime
            ),
            # the menu is a sequence of row builders (no public build())
            components=cast(Any, menu),
        )
        try:
            await menu.attach(ctx.client, timeout=30)
        except asyncio.TimeoutError:
            await ctx.edit_response(
                INITIAL_RESPONSE_IDENTIFIER, component=None
            )


@experience.register
class Resync(
    lightbulb.SlashCommand,
    name="resync",
    description="Rebuild every member's lifetime exp from the exp logs.",
    hooks=[utils.OWNER_ONLY],
):
    """Rebuild every member's lifetime exp from the exp logs."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Confirm, then rebuild lifetime exp from the logs."""
        bot = utils.bot_from(ctx)
        if not await utils.author_confirm(ctx):
            return
        async with command_window(ctx) as window:
            window.info("Fetching exp logs...")
            await window.flush()  # ack early before the big UPDATE
            await exp_db.sync_with_exp_logs(bot.db)
            window.success("Lifetime exp synced.")


experience_quiet = experience.subgroup(
    "quiet", "Channels where level-up messages are suppressed."
)


@experience_quiet.register
class Quiet(
    lightbulb.SlashCommand,
    name="list",
    description="List channels where level-up messages are suppressed.",
):
    """List channels where level-up messages are suppressed."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Echo the current quiet list."""
        bot = utils.bot_from(ctx)
        quiets: list[int] = await bot.settings.get("level.quiet", []) or []
        await ctx.respond(str(quiets))


@experience_quiet.register
class QuietAdd(
    lightbulb.SlashCommand,
    name="add",
    description="Suppress level-up messages in a channel.",
    hooks=[utils.ADMIN_ONLY],
):
    """Suppress level-up messages in a channel."""

    channel = lightbulb.channel(
        "channel",
        "The channel to quiet",
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Add a channel to the quiet list."""
        bot = utils.bot_from(ctx)
        quiets: list[int] = await bot.settings.get("level.quiet", []) or []
        if self.channel.id in quiets:
            await window_warn(ctx, "Channel already in the quiet list")
            return
        quiets.append(self.channel.id)
        await bot.settings.set("level.quiet", quiets)
        await window_success(
            ctx, f"Added {self.channel.mention} to the quiet list"
        )


@experience_quiet.register
class QuietDel(
    lightbulb.SlashCommand,
    name="del",
    description="Un-suppress level-up messages in a channel.",
    hooks=[utils.ADMIN_ONLY],
):
    """Un-suppress level-up messages in a channel."""

    channel = lightbulb.channel(
        "channel",
        "The channel to un-quiet",
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Remove a channel from the quiet list."""
        bot = utils.bot_from(ctx)
        quiets: list[int] = await bot.settings.get("level.quiet", []) or []
        if self.channel.id not in quiets:
            await window_warn(ctx, "Channel was never in the quiet list")
            return
        quiets.remove(self.channel.id)
        await bot.settings.set("level.quiet", quiets)
        await window_success(
            ctx, f"Removed {self.channel.mention} from the quiet list"
        )


loader.command(experience)


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
    board = await leaderboard.focus_board(
        bot,
        rows,
        user.id,
        headers=["Rank", "Exp", "Lv", "User"],
        align=["<", ">", ">", ">"],
        max_padding=[0, 0, 0, 16],
        level_of=levels.level_from_exp,
    )
    if board is None:
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
    scoreboard_s = board.text
    lvl = board.level
    exp = board.value
    rank = board.rank

    # member stats
    from core.models import WindowEnum
    from plugins.ranks.db import of_member

    rid = await of_member(
        bot.db,
        user.id,
        mode=WindowEnum.LIFETIME if lifetime else WindowEnum.SEASONAL,
    )
    role = None
    guild = bot.guild
    if rid is not None and guild is not None:
        role = bot.cache.get_role(rid)

    if lifetime:
        total = await exp_db.total_members(bot.db)
    else:
        now = pendulum.now("UTC")
        total = await exp_db.seasonal_total_members(
            bot.db, now.year, utils.month2season(now.month)
        )

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

		You are currently in the top `{utils.top_percent(rank, total)}%` of all members!
		```ansi\n{scoreboard_s}```"""
    return embed


async def _top_embed(
    ctx: lightbulb.Context,
    date: pendulum.DateTime | None,
    rows: list[tuple[int, int, int]],
    page: int,
    *,
    lifetime: bool = False,
) -> hikari.Embed:
    """The leaderboard pager embed (pageable via TopMenu)."""
    bot = utils.bot_from(ctx)
    embed = hikari.Embed(color=_COLOR)
    embed.set_author(
        name="Club Cirno Leaderboards", icon=_SCOREBOARD_STAMP
    )

    if not rows:
        scoreboard_s = (
            "No experience has been logged yet."
            if lifetime
            else "No data has been logged during this time period."
        )
    else:
        top_user = await utils.find_user(bot, rows[0][1])
        if top_user:
            embed.set_thumbnail(str(top_user.display_avatar_url))

        subset = rows[(page - 1) * 10 : page * 10]
        ranks = [r[0] for r in subset]
        uids = [r[1] for r in subset]
        exps = [r[2] for r in subset]
        lvls = [levels.level_from_exp(e) for e in exps]
        names = await leaderboard.resolve_names(bot, uids)

        window = list(zip(ranks, exps, lvls, names))
        headers = ["Rank", "Exp", "Lv", "User"]
        align = ["<", ">", ">", ">"]
        max_padding = [0, 0, 0, 16]
        author_id = (ctx.member or ctx.user).id
        scoreboard = leaderboard.format(
            window,
            headers,
            align=align,
            max_padding=max_padding,
            highlight=uids.index(author_id) if author_id in uids else None,
            color=True,
        )
        scoreboard_s = "\n".join(scoreboard)

    embed.description = f"""
		{_window_header(date, page, lifetime=lifetime)}
		```ansi\n{scoreboard_s}```"""
    return embed


def _window_header(
    date: pendulum.DateTime | None, page: int, *, lifetime: bool
) -> str:
    """The embed's window lines: all-time, or year/season, plus the page."""
    if lifetime:
        lines = ["Window: **`All time`**", f"Page: **`{page}`**"]
    else:
        assert date is not None  # seasonal boards always carry a date
        lines = [
            f"Year: **`{date.year}`**",
            f"Season: **`{utils.month2season(date.month) + 1}`**",
            f"Page: **`{page}`**",
        ]
    return "\n\t\t".join(lines)


class TopMenu(lightbulb.components.Menu):
    """Leaderboard pager: page ◀/▶, plus season ⬅/➡ in seasonal mode."""

    def __init__(
        self,
        bot: CazzuBot,
        ctx: lightbulb.Context,
        date: pendulum.DateTime | None,
        rows: list[tuple[int, int, int]],
        page: int = 1,
        *,
        lifetime: bool = False,
    ) -> None:
        """Build the pager buttons and remember the board's state."""
        super().__init__()
        self.bot = bot
        self.ctx = ctx
        self.author_id = (ctx.member or ctx.user).id
        self.date = date
        self.rows = rows
        self.page = page
        self.lifetime = lifetime
        # the lifetime board is one flat window — season buttons would
        # have nothing to step through, so it gets the page pair only
        if not lifetime:
            self.add_interactive_button(
                hikari.ButtonStyle.SECONDARY, self._prev_season, emoji="⬅"
            )
        self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self._prev_page, emoji="◀"
        )
        self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, self._next_page, emoji="▶"
        )
        if not lifetime:
            self.add_interactive_button(
                hikari.ButtonStyle.SECONDARY, self._next_season, emoji="➡"
            )

    async def _edit(self, mctx: lightbulb.components.MenuContext) -> None:
        """Re-render the embed at the current page (atomic ack+edit)."""
        embed = await _top_embed(
            self.ctx,
            self.date,
            self.rows,
            self.page,
            lifetime=self.lifetime,
        )
        # respond(edit=True) is the atomic ack+edit: lightbulb menu clicks
        # arrive un-acked, and edit_response on the un-acked interaction 404s
        await mctx.respond(edit=True, embed=embed)

    async def _deny(self, mctx: lightbulb.components.MenuContext) -> None:
        """Reply that the leaderboard is not the clicker's to page."""
        await mctx.respond(
            "This leaderboard is not yours to page.",
            flags=hikari.MessageFlag.EPHEMERAL,
        )

    async def _guard(self, mctx: lightbulb.components.MenuContext) -> bool:
        """True when the clicker may page this leaderboard."""
        if mctx.interaction.user.id != self.author_id:
            await self._deny(mctx)
            return False
        return True

    async def _step_season(
        self, mctx: lightbulb.components.MenuContext, months: int
    ) -> None:
        """Shift the seasonal window; unreachable on the lifetime board."""
        if not await self._guard(mctx):
            return
        if self.date is None:
            return
        self.date = self.date.add(months=months)
        self.rows = await exp_db.seasonal_ranked(
            self.bot.db,
            self.date.year,
            utils.month2season(self.date.month),
        )
        self.page = 1
        await self._edit(mctx)

    async def _prev_season(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        await self._step_season(mctx, -3)

    async def _prev_page(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        if not await self._guard(mctx):
            return
        self.page = max(self.page - 1, 1)
        await self._edit(mctx)

    async def _next_page(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        if not await self._guard(mctx):
            return
        # ceil(rows / 10): a floor division here strands the trailing
        # (rows % 10) entries on an unreachable page (12 rows -> 2 pages)
        self.page = min(
            self.page + 1, max((len(self.rows) - 1) // 10 + 1, 1)
        )
        await self._edit(mctx)

    async def _next_season(
        self, mctx: lightbulb.components.MenuContext
    ) -> None:
        await self._step_season(mctx, 3)
