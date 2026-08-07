"""Experience cog — message exp pipeline, membership card, leaderboards."""

import asyncio
from math import trunc
from typing import Any

import discord
import pendulum
from discord.ext import commands

from cazzubot import leaderboard, levels, utils
from cazzubot.bot import CazzuBot
from cazzubot.window import command_window, window_success, window_warn
from typing_extensions import override

from . import db as exp_db
from .logic import award_exp

# -- experience rates live in ``plugins/experience/logic.py`` --------------

_SCOREBOARD_STAMP = (
    "https://cdn.discordapp.com/emojis/695126165756837999.webp"
    "?size=160&quality=lossless"
)


class TopView(discord.ui.View):
    """Seasonal leaderboard pager: page ◀/▶ and season ⬅/➡ buttons."""

    def __init__(
        self,
        cog: "ExperienceCog",
        ctx: commands.Context[CazzuBot],
        date: pendulum.DateTime,
        rows: list[tuple[int, int, int]],
        page: int = 1,
        *,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.cog = cog
        self.ctx = ctx
        self.author_id = ctx.author.id
        self.date = date
        self.rows = rows
        self.page = page
        self.message: discord.Message | None = None

    async def _edit(self, interaction: discord.Interaction) -> None:
        embed = await self.cog.top_embed(
            self.ctx, self.date, self.rows, self.page
        )
        await interaction.response.edit_message(embed=embed)

    async def _deny(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "This leaderboard is not yours to page.", ephemeral=True
        )

    @discord.ui.button(emoji="⬅", style=discord.ButtonStyle.secondary)
    async def prev_season(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[Any],
    ) -> None:
        if interaction.user.id != self.author_id:
            await self._deny(interaction)
            return
        self.date = self.date.subtract(months=3)
        self.rows = await exp_db.seasonal_ranked(
            self.cog.bot.db, self.date.year, (self.date.month - 1) // 3
        )
        self.page = 1
        await self._edit(interaction)

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary)
    async def prev_page(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[Any],
    ) -> None:
        if interaction.user.id != self.author_id:
            await self._deny(interaction)
            return
        self.page = max(self.page - 1, 1)
        await self._edit(interaction)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary)
    async def next_page(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[Any],
    ) -> None:
        if interaction.user.id != self.author_id:
            await self._deny(interaction)
            return
        self.page = min(self.page + 1, max(len(self.rows) // 10, 1))
        await self._edit(interaction)

    @discord.ui.button(emoji="➡", style=discord.ButtonStyle.secondary)
    async def next_season(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button[Any],
    ) -> None:
        if interaction.user.id != self.author_id:
            await self._deny(interaction)
            return
        self.date = self.date.add(months=3)
        self.rows = await exp_db.seasonal_ranked(
            self.cog.bot.db, self.date.year, (self.date.month - 1) // 3
        )
        self.page = 1
        await self._edit(interaction)

    @override
    async def on_timeout(self) -> None:
        """Strip the buttons once idle."""
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.NotFound:
                pass


class ExperienceCog(commands.Cog):
    """Experience scoring and leaderboards."""

    def __init__(self, bot: CazzuBot) -> None:
        self.bot = bot
        self._exp_locks: dict[int, asyncio.Lock] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Award exp based on daily message count; handle level/rank ups."""
        if message.author.bot:
            return
        if (
            self.bot.user is not None
            and message.author.id == self.bot.user.id
        ):
            return
        if (
            message.guild is None
            or message.guild.id != self.bot.config.guild_id
        ):
            return

        # serialize exp updates per user so concurrent messages can't race
        # the msg_cnt/lifetime read-modify-write
        lock = self._exp_locks.setdefault(
            message.author.id, asyncio.Lock()
        )
        async with lock:
            await self._award_exp(message)

    async def _award_exp(self, message: discord.Message) -> None:
        """Controller: resolve, call the service, present the outcome."""
        now = pendulum.now("UTC")
        uid = message.author.id
        result = await award_exp(self.bot.db, uid=uid, now=now)
        if result is None:
            return  # cooldown active or row missing

        # presentation — level-up/rank-up notifications (cross-plugin)
        from plugins.levels.logic import handle_level_up
        from plugins.ranks.logic import handle_ranks

        await handle_level_up(
            self.bot, message, result.seasonal_level, delete_after=7
        )
        await handle_ranks(
            self.bot,
            message,
            result.seasonal_level,
            result.lifetime_level,
            delete_after=7,
        )

    # -- commands ----------------------------------------------------------

    @commands.hybrid_group(aliases=["xp", "experience"])
    async def exp(
        self,
        ctx: commands.Context[CazzuBot],
        *,
        user: discord.Member | None = None,
    ) -> None:
        """Show this season's experience and leaderboard."""
        target = user or ctx.author
        now = pendulum.now("UTC")
        rows = await exp_db.seasonal_ranked(
            self.bot.db, now.year, (now.month - 1) // 3
        )
        await ctx.send(
            embed=await self._prepare_personal_summary(ctx, target, rows)
        )

    @exp.command(name="lifetime")
    async def exp_lifetime(
        self,
        ctx: commands.Context[CazzuBot],
        *,
        user: discord.Member | None = None,
    ) -> None:
        """Lifetime experience variant."""
        target = user or ctx.author
        rows = await exp_db.lifetime_ranked(self.bot.db)
        await ctx.send(
            embed=await self._prepare_personal_summary(
                ctx, target, rows, lifetime=True
            )
        )

    async def _prepare_personal_summary(
        self,
        ctx: commands.Context[CazzuBot],
        user: discord.Member | discord.User,
        rows: list[tuple[int, int, int]],
        *,
        lifetime: bool = False,
    ) -> discord.Embed:
        """The "Club Membership Card" embed."""
        uid = user.id
        uids = [r[1] for r in rows]
        if uid not in uids:
            embed = discord.Embed(
                description=f"{user.display_name} has no experience yet.",
                color=discord.Color.from_str("#a2dcf7"),
            )
            embed.set_author(
                name=f"{user.display_name}'s Club Membership Card",
                icon_url=_SCOREBOARD_STAMP,
            )
            embed.set_thumbnail(url=user.display_avatar.url)
            return embed

        uid_index = uids.index(uid)
        subset, subset_i = leaderboard.create_focus_subset(rows, uid_index)

        ranks = [r[0] for r in subset]
        exps = [r[2] for r in subset]
        lvls = [levels.level_from_exp(e) for e in exps]
        names: list[str] = []
        for uid_ in [r[1] for r in subset]:
            found = await utils.find_user(self.bot, ctx, uid_)
            names.append(found.display_name if found else str(uid_))

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
            self.bot.db,
            uid,
            mode=WindowEnum.LIFETIME if lifetime else WindowEnum.SEASONAL,
        )
        role = None
        if rid is not None and ctx.guild is not None:
            role = ctx.guild.get_role(rid)

        lvl = lvls[subset_i]
        exp = exps[subset_i]
        rank = ranks[subset_i]

        if lifetime:
            total = await exp_db.total_members(self.bot.db)
        else:
            now = pendulum.now("UTC")
            total = await exp_db.seasonal_total_members(
                self.bot.db, now.year, (now.month - 1) // 3
            )

        percentile = utils.calc_percentile(rank, total)

        embed = discord.Embed(color=discord.Color.from_str("#a2dcf7"))
        embed.set_author(
            name=f"{user.display_name}'s Club Membership Card",
            icon_url=_SCOREBOARD_STAMP,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.description = f"""
		Rank: {role.mention if role else "`None`"}
		Level: **`{lvl:,}`**
		Experience: **`{exp:,}`**

		You are currently the `{utils.ordinal(trunc(percentile))}` percentile of all members!
		```py\n{scoreboard_s}```"""
        return embed

    @exp.command(name="top")
    async def exp_top(
        self,
        ctx: commands.Context[CazzuBot],
        year: int | None = None,
        season: int | None = None,
        page: int | None = None,
    ) -> None:
        """Display the seasonal experience leaderboard (button-paged)."""
        now = pendulum.now("UTC")
        year = year or now.year
        season = season or (now.month - 1) // 3 + 1
        page = page or 1

        if not 1 <= season <= 4:
            raise commands.BadArgument(
                f"Season {season} is not a valid number (1-4)"
            )
        if not 2023 <= year <= now.year:
            raise commands.BadArgument(
                f"Year {year} is not a valid year, or is too early."
            )
        if page <= 0:
            raise commands.BadArgument(
                f"Page {page} must be greater than 0."
            )

        date = pendulum.datetime(year, ((season - 1) * 3) + 1, 1)
        rows = await exp_db.seasonal_ranked(
            self.bot.db, date.year, (date.month - 1) // 3
        )

        view = TopView(self, ctx, date, rows, page=page)
        msg = await ctx.send(
            embed=await self.top_embed(ctx, date, rows, page), view=view
        )
        view.message = msg
        await view.wait()

    async def top_embed(
        self,
        ctx: commands.Context[CazzuBot],
        date: pendulum.DateTime,
        rows: list[tuple[int, int, int]],
        page: int,
    ) -> discord.Embed:
        embed = discord.Embed(color=discord.Color.from_str("#a2dcf7"))
        embed.set_author(
            name="Club Cirno Leaderboards", icon_url=_SCOREBOARD_STAMP
        )

        if not rows:
            scoreboard_s = (
                "No data has been logged during this time period."
            )
        else:
            if rows and rows[0]:
                top_user = await utils.find_user(self.bot, ctx, rows[0][1])
                if top_user:
                    embed.set_thumbnail(url=top_user.display_avatar.url)

            subset = rows[(page - 1) * 10 : page * 10]
            ranks = [r[0] for r in subset]
            uids = [r[1] for r in subset]
            exps = [r[2] for r in subset]
            lvls = [levels.level_from_exp(e) for e in exps]
            names: list[str] = []
            for id_ in uids:
                user = await utils.find_user(self.bot, ctx, id_)
                names.append(user.display_name if user else str(id_))

            window = list(zip(ranks, exps, lvls, names))
            headers = ["Rank", "Exp", "Lv", "User"]
            align = ["<", ">", ">", ">"]
            max_padding = [0, 0, 0, 16]
            scoreboard = leaderboard.format(
                window, headers, align=align, max_padding=max_padding
            )
            if ctx.author.id in uids:
                col_widths = leaderboard.calc_max_col_width(
                    window, headers, max_padding
                )
                leaderboard.highlight_row(
                    scoreboard, uids.index(ctx.author.id), col_widths
                )
            scoreboard_s = "\n".join(scoreboard)

        embed.description = f"""
		Year: **`{date.year}`**
		Season: **`{(date.month - 1) // 3 + 1}`**
		Page: **`{page}`**
		```py\n{scoreboard_s}```"""
        return embed

    @exp.command(name="resync")
    @commands.is_owner()
    async def exp_resync(self, ctx: commands.Context[CazzuBot]) -> None:
        """Rebuild every member's lifetime exp from the exp logs."""
        if not await utils.author_confirm(ctx):
            return
        async with command_window(ctx) as window:
            window.info("Fetching exp logs...")
            await window.flush()  # ack early before the big UPDATE
            await exp_db.sync_with_exp_logs(self.bot.db)
            window.success("Lifetime exp synced.")

    @exp.group(name="quiet")
    async def quiet(self, ctx: commands.Context[CazzuBot]) -> None:
        """List channels where level-up messages are suppressed."""
        quiets: list[int] = (
            await self.bot.settings.get("level.quiet", []) or []
        )
        await ctx.send(str(quiets))

    @quiet.command(name="add")
    @commands.has_permissions(administrator=True)
    async def quiet_add(
        self, ctx: commands.Context[CazzuBot], channel: discord.TextChannel
    ) -> None:
        quiets: list[int] = (
            await self.bot.settings.get("level.quiet", []) or []
        )
        if channel.id in quiets:
            await window_warn(ctx, "Channel already in the quiet list")
            return
        quiets.append(channel.id)
        await self.bot.settings.set("level.quiet", quiets)
        await window_success(
            ctx, f"Added {channel.mention} to the quiet list"
        )

    @quiet.command(name="del")
    @commands.has_permissions(administrator=True)
    async def quiet_del(
        self, ctx: commands.Context[CazzuBot], channel: discord.TextChannel
    ) -> None:
        quiets: list[int] = (
            await self.bot.settings.get("level.quiet", []) or []
        )
        if channel.id not in quiets:
            await window_warn(ctx, "Channel was never in the quiet list")
            return
        quiets.remove(channel.id)
        await self.bot.settings.set("level.quiet", quiets)
        await window_success(
            ctx, f"Removed {channel.mention} from the quiet list"
        )
