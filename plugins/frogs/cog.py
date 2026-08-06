"""Frogs cog — profile, register/configure spawns, consume, dev commands."""

import json
import logging
from enum import Enum
from math import trunc

import discord
import pendulum
from discord.ext import commands

from cazzubot import leaderboard, templates, timeparse, utils
from cazzubot.bot import CazzuBot
from cazzubot.window import command_window, window_success
from cazzubot.models import (
    FrogTypeEnum,
    MemberExpLogSourceEnum,
)

from . import db as frog_db
from . import factory

_log = logging.getLogger(__name__)

_SCOREBOARD_STAMP = (
    "https://cdn.discordapp.com/emojis/752290769712316506.webp"
    "?size=160&quality=lossless"
)


class _ExpFrog(Enum):
    """Exp granted per frog consumed."""

    NORMAL = 10
    FROZEN = 3


class FrogsCog(commands.Cog):
    """Frog token economy."""

    def __init__(self, bot: CazzuBot) -> None:
        self.bot = bot

    @commands.hybrid_group(aliases=["frogs"])
    async def frog(
        self,
        ctx: commands.Context[CazzuBot],
        *,
        member: discord.Member | None = None,
    ) -> None:
        """Show this user's current frog profile."""
        target = member or ctx.author
        now = pendulum.now("UTC")
        rows = await frog_db.seasonal_ranked(
            self.bot.db, now.year, (now.month - 1) // 3
        )
        if not rows:
            await ctx.send("No one has yet captured frogs in this server!")
            return
        if target.id not in [r[1] for r in rows]:
            await ctx.send(
                "You have not yet captured any frogs this season!"
            )
            return
        await ctx.send(
            embed=await self._prepare_personal_summary(ctx, target, rows)
        )

    @frog.command(name="lifetime")
    async def frog_lifetime(
        self,
        ctx: commands.Context[CazzuBot],
        *,
        user: discord.Member | None = None,
    ) -> None:
        """Lifetime frog variant."""
        target = user or ctx.author
        rows = await frog_db.lifetime_ranked(self.bot.db)
        if not rows:
            await ctx.send("No one has yet captured frogs in this server!")
            return
        if target.id not in [r[1] for r in rows]:
            await ctx.send(
                "You have not yet captured any frogs this season!"
            )
            return
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
        """The "Frog Capture Permit" embed."""
        uid = user.id
        uids = [r[1] for r in rows]
        uid_index = uids.index(uid)
        subset, subset_i = leaderboard.create_focus_subset(rows, uid_index)

        ranks = [r[0] for r in subset]
        frog_cnt = [r[2] for r in subset]
        names: list[str] = []
        for uid_ in [r[1] for r in subset]:
            member = await utils.find_user(self.bot, ctx, uid_)
            names.append(member.display_name if member else str(uid_))

        window = list(zip(ranks, frog_cnt, names))
        headers = ["Rank", "Frogs", "User"]
        align = ["<", ">", ">"]
        max_padding = [0, 0, 16]

        scoreboard = leaderboard.format(
            window, headers, align=align, max_padding=max_padding
        )
        col_widths = leaderboard.calc_max_col_width(
            window, headers, max_padding
        )
        leaderboard.highlight_row(scoreboard, subset_i, col_widths)
        scoreboard_s = "\n".join(scoreboard)

        user_frog_cnt = frog_cnt[subset_i]
        normal_inv = await frog_db.get_frogs(
            self.bot.db, uid, FrogTypeEnum.NORMAL
        )
        frozen_inv = await frog_db.get_frogs(
            self.bot.db, uid, FrogTypeEnum.FROZEN
        )
        rank = ranks[subset_i]

        now = pendulum.now("UTC")
        if lifetime:
            total = await frog_db.total_members(self.bot.db)
        else:
            total = await frog_db.seasonal_total_members(
                self.bot.db, now.year, (now.month - 1) // 3
            )

        percentile = utils.calc_percentile(rank, total)

        embed = discord.Embed(color=discord.Color.from_str("#a2dcf7"))
        embed.set_author(
            name=f"{user.display_name}'s Frog Capture Permit",
            icon_url=_SCOREBOARD_STAMP,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.description = f"""
		Total Frogs Captured: **`{user_frog_cnt}`**

		**__Inventory__**
		Frogs (Seasonal): **`{normal_inv}`**
		Frogs (Frozen): **`{frozen_inv}`**

		You are currently the `{utils.ordinal(trunc(percentile))}` percentile of all members!
		```py\n{scoreboard_s}```
		"""
        return embed

    # -- configuration ------------------------------------------------------

    @frog.command(name="register")
    @commands.has_permissions(administrator=True)
    async def frog_register(
        self,
        ctx: commands.Context[CazzuBot],
        interval: str,
        persist: str = "30",
        fuzzy: float = 0.5,
        channel: discord.TextChannel | None = None,
    ) -> None:
        """Register this channel as a frog spawn channel.

        Interval uses natural duration processing, at least 1 frog every interval.
        Persist is in seconds, how many seconds a frog stays until disappearing.
        Fuzzy is a decimal percent, the randomness of spawning intervals.
        """
        cid = (channel or ctx.channel).id

        try:
            interval_s = timeparse.parse_duration(interval).in_seconds()
        except timeparse.InvalidTimeError as err:
            raise commands.BadArgument(
                f"Interval {interval} is not a valid time."
            ) from err

        if not self.bot.config.debug and interval_s < 60:
            raise commands.BadArgument(
                "Interval must be greater than 60 seconds."
            )

        try:
            persist_s = timeparse.parse_duration(persist).in_seconds()
        except timeparse.InvalidTimeError as err:
            raise commands.BadArgument(
                f"Persist {persist} is not a valid time."
            ) from err

        if not self.bot.config.debug and not 3 <= persist_s <= 120:
            raise commands.BadArgument(
                "Persist must be between 3 and 120 seconds."
            )
        if not self.bot.config.debug and not 0 <= fuzzy <= 1:
            raise commands.BadArgument("Fuzzy must be between 0 and 1.")

        await frog_db.upsert_spawn(
            self.bot.db, cid, interval_s, persist_s, fuzzy
        )
        await factory.reset_frog_tasks(self.bot)
        await window_success(ctx, "Spawn channel registered")

    @frog.command(name="clear")
    @commands.has_permissions(administrator=True)
    async def frog_clear(self, ctx: commands.Context[CazzuBot]) -> None:
        """Remove all frog settings and stop frog spawning."""
        await frog_db.clear_spawns(self.bot.db)
        await self.bot.scheduler.drop_tag("frog")
        await window_success(ctx, "Cleared all frog spawn channels")

    @frog.group(name="set")
    @commands.has_permissions(administrator=True)
    async def frog_set(self, _ctx: commands.Context[CazzuBot]) -> None:
        pass

    @frog_set.command(name="message", aliases=["msg"])
    async def frog_set_message(
        self, ctx: commands.Context[CazzuBot], *, message: str
    ) -> None:
        """Set the capture message JSON."""
        decoded = templates.verify(
            message, factory.formatter, member=ctx.author
        )
        await frog_db.set_message(self.bot.settings, decoded)
        await window_success(ctx, "Capture message set")

    @frog_set.command(name="enabled", aliases=["on"])
    async def frog_set_enabled(
        self, ctx: commands.Context[CazzuBot], val: bool
    ) -> None:
        """Enable/disable frog spawns (re-queues or clears spawn tasks)."""
        await frog_db.set_enabled(self.bot.settings, val)
        await factory.reset_frog_tasks(self.bot)
        await window_success(
            ctx,
            "Frog spawning enabled" if val else "Frog spawning disabled",
        )

    @frog.command(name="demo")
    @commands.has_permissions(administrator=True)
    async def frog_demo(self, ctx: commands.Context[CazzuBot]) -> None:
        """Preview the capture message as yourself."""
        msg_json = await frog_db.get_message(self.bot.settings)
        if not msg_json:
            await ctx.send("No capture message has been set.")
            return
        utils.deep_map(msg_json, factory.formatter, member=ctx.author)
        await templates.send(ctx, msg_json)

    @frog.command(name="raw")
    @commands.has_permissions(administrator=True)
    async def frog_raw(self, ctx: commands.Context[CazzuBot]) -> None:
        """Dump the raw stored capture message JSON."""
        msg_json = await frog_db.get_message(self.bot.settings)
        await ctx.send(f"```{json.dumps(msg_json, indent=2)}```")

    # -- consumption --------------------------------------------------------

    @frog.command(name="consume")
    async def frog_consume(
        self,
        ctx: commands.Context[CazzuBot],
        amount: int = 1,
        frog_type: FrogTypeEnum = FrogTypeEnum.NORMAL,
    ) -> None:
        """Consume frogs for seasonal experience (10 exp normal / 3 frozen)."""
        if amount < 1:
            raise commands.BadArgument(
                "Amount of frogs to consume must be greater than 0."
            )

        uid = ctx.author.id
        balance = await frog_db.get_frogs(self.bot.db, uid, frog_type)
        if balance < amount:
            raise commands.BadArgument(
                f"Member does not have enough frogs ({balance}) to consume."
            )

        exp_per = _ExpFrog[frog_type.name].value
        total_exp = exp_per * amount
        now = pendulum.now("UTC")

        from plugins.experience.db import seasonal_exp

        exp_old = await seasonal_exp(
            self.bot.db, uid, now.year, (now.month - 1) // 3
        )

        desc = (
            f"You are about to consume **`{amount}` {frog_type.value} "
            f"frog(s)**.\n\n"
            f"These types of frogs grant `{exp_per}` exp per frog, for a "
            f"total of **`{total_exp}`**.\n\n"
            f"Resulting frogs\n**`{balance}`** -> **`{balance - amount}`**\n"
            f"Resulting exp\n**`{exp_old:,}`** -> "
            f"**`{exp_old + total_exp:,}`**\n\n"
            "Please confirm."
        )
        embed = utils.prepare_embed("**Confirmation**", desc)
        embed.set_thumbnail(url="https://i.imgur.com/ybxI7pu.png")
        view = utils.ConfirmView(uid, timeout=120, delete_after=False)
        msg = await ctx.send(embed=embed, view=view)
        await view.wait()
        if view.value is None or not view.value:
            await msg.delete()
            return

        # re-check balance at the very moment of consumption
        balance_now = await frog_db.get_frogs(self.bot.db, uid, frog_type)
        if balance_now < amount:
            raise commands.BadArgument(
                f"Member does not have enough frogs ({balance_now}) "
                + "to consume."
            )

        now = pendulum.now("UTC")
        from plugins.experience.db import add_exp_log

        await add_exp_log(
            self.bot.db,
            uid,
            total_exp,
            now,
            source=MemberExpLogSourceEnum.FROG,
        )
        await frog_db.modify_frog(
            self.bot.db, uid, modify=-amount, frog_type=frog_type
        )

        embed_post = utils.prepare_embed(
            "Frog(s) have been consumed!",
            f"Resulting {frog_type.value} frogs\n"
            + f"**`{balance}`** -> **`{balance - amount}`**",
        )
        embed_post.set_thumbnail(url="https://i.imgur.com/kCHjymJ.png")
        await msg.edit(embed=embed_post)

    # -- owner/debug --------------------------------------------------------

    @frog.command(name="spawn")
    @commands.is_owner()
    async def frog_spawn(self, ctx: commands.Context[CazzuBot]) -> None:
        """Force-spawn a frog in this channel."""
        # the frog message is the success signal — no separate confirmation
        await factory.spawn_and_wait(
            self.bot, 30, ctx.interaction, cid=ctx.channel.id
        )

    @frog.command(name="fake")
    @commands.is_owner()
    async def frog_fake(self, ctx: commands.Context[CazzuBot]) -> None:
        """Post a fake frog with its capture button."""
        await factory.spawn_and_wait(
            self.bot, 30, ctx.interaction, cid=ctx.channel.id
        )

    @frog.command(name="resync")
    @commands.is_owner()
    async def frog_resync(self, ctx: commands.Context[CazzuBot]) -> None:
        """Rebuild lifetime capture counts from the frog logs."""
        if not await utils.author_confirm(ctx):
            return
        async with command_window(ctx) as window:
            window.info("Fetching frog logs...")
            await window.flush()  # ack early before the big UPDATE
            await frog_db.sync_with_frog_logs(self.bot.db)
            window.success("Lifetime captures synced.")
