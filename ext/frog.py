"""Allows the hotswapping of extensions/cogs."""

import json
import logging
import os
import random
from asyncio import TimeoutError
from enum import Enum
from math import trunc
from typing import TYPE_CHECKING

import discord
import pendulum
from asyncpg import Record
from discord.ext import commands, tasks
from pendulum import DateTime

from main import CazzuBot
from src import db, frog, frog_factory, leaderboard, user_json, utility
from src.custom_converters import PositiveInt
from src.ntlp import InvalidTimeError, parse_duration


_log = logging.getLogger(__name__)

_SCOREBOARD_STAMP = "https://cdn.discordapp.com/emojis/752290769712316506.webp?size=160&quality=lossless"


class _ExpFrog(Enum):
    NORMAL: int = 30
    FROZEN: int = 15


class Frog(commands.Cog):
    def __init__(self, bot: CazzuBot):
        self.bot: CazzuBot = bot
        self.check_spawn_frog.start()

    async def cog_load(self):
        await frog_factory.reset_frog_tasks(self.bot)

    async def cog_unload(self):
        self.check_spawn_frog.cancel()

    # def cog_check(self, ctx):
    #     return ctx.author.id == self.bot.owner_id

    @tasks.loop(seconds=1)
    async def check_spawn_frog(self):
        """Check at regular invervals if we need to spawn a frog.

        We know we need to spawn a frog if the time now is past the the "run_at" under
        the task query with tags "frog".
        """
        # _log.info("Checking if frog can spawn...")

        await frog_factory.check_frog_spawn(self.bot)

    @check_spawn_frog.before_loop
    async def before_check_frog_spawn(self):
        await self.bot.wait_until_ready()

    @commands.group(invoke_without_command=True, aliases=["frogs"])
    async def frog(self, ctx: commands.Context, *, member: discord.Member = None):
        """Show this user's current frog profile."""
        if member is None:
            member = ctx.message.author

        now = pendulum.now()
        gid = ctx.guild.id
        uid = member.id

        rows = await db.member_frog.get_members_frog_seasonal_by_month(
            self.bot.pool, gid, now.year, now.month
        )

        for row in rows:
            _log.debug(f"{list(row.values())=}")

        # New season, no data on user yet
        # It would be better to just ignore all things leaderboards, but still show
        # all other status, but this will work for now...
        #
        # This is an issue with c!xp as well...
        if not rows:
            await ctx.send("No one has yet captured frogs in this server!")
            return

        _, uids, _ = zip(*rows)
        if uid not in uids:
            await ctx.send("You have not yet captured any frogs this season!")
            return

        embed = await self._prepare_personal_summary(ctx, member, rows)

        await ctx.send(embed=embed)

    @frog.command(name="lifetime")
    async def frog_lifetime(
        self, ctx: commands.Context, *, user: discord.Member = None
    ):
        """Lifetime frog variant."""
        if user is None:
            user = ctx.message.author

        gid = ctx.guild.id
        rows = await db.member_frog.get_all_member_frogs_ranked(self.bot.pool, gid)

        # New season, no data on user yet
        # It would be better to just ignore all things leaderboards, but still show
        # all other status, but this will work for now...
        #
        # This is an issue with c!xp as well...
        if not rows:
            await ctx.send("No one has yet captured frogs in this server!")
            return

        _, uids, _ = zip(*rows)
        if user.id not in uids:
            await ctx.send("You have not yet captured any frogs this season!")
            return

        embed = await self._prepare_personal_summary(
            ctx, user, rows, db.table.WindowEnum.LIFETIME
        )

        await ctx.send(embed=embed)

    async def _prepare_personal_summary(
        self,
        ctx: commands.Context,
        user: discord.Member,
        data: list[Record],
        mode: db.table.WindowEnum = db.table.WindowEnum.SEASONAL,
    ) -> discord.Embed:
        """Return embed for frog summary on user.

        data: raw query result, formatted as (rank, uid, frog)
        """
        uid = user.id

        # Prepare leaderboard
        uid_index = [r["uid"] for r in data].index(uid)
        _log.debug(f"{uid_index=}")
        subset, subset_i = leaderboard.create_data_subset(data, uid_index)
        for s in subset:
            _log.debug(f"{s=}")

        # Transpose, turn uid into usernames
        ranks, uids, frog_cnt = zip(*subset)

        names = [await utility.find_username(self.bot, ctx, id) for id in uids]

        # Transpose back to row-major
        window = list(zip(ranks, frog_cnt, names))

        # Generate leaderboard
        headers = ["Rank", "Frogs", "User"]
        align = ["<", ">", ">"]
        max_padding = [0, 0, 16]

        raw_scoreboard = leaderboard.format(
            window, headers, align=align, max_padding=max_padding
        )

        col_widths = leaderboard.calc_max_col_width(data, headers, max_padding)

        for e in raw_scoreboard:
            _log.debug(f"{e}")
        leaderboard.highlight_row(raw_scoreboard, subset_i, col_widths)
        scoreboard_s = "\n".join(raw_scoreboard)

        # Other Preparation
        gid = ctx.guild.id

        # Prepare Embed
        embed = discord.Embed()
        user_frog_cnt = frog_cnt[subset_i]
        user_frog_inv = await db.member_frog.get_frogs(self.bot.pool, gid, uid)
        rank = ranks[subset_i]

        if mode is db.table.WindowEnum.SEASONAL:
            now = pendulum.now()
            year = now.year
            month = now.month

            total_member_count = (
                await db.member_frog_log.get_seasonal_total_members_by_month(
                    self.bot.pool, gid, year, month
                )
            )
        elif mode is db.table.WindowEnum.LIFETIME:
            total_member_count = await db.member_frog_log.get_total_members(
                self.bot.pool, gid
            )

        percentile = utility.calc_percentile(rank, total_member_count)

        embed.set_author(
            name=f"{user.display_name}'s Frog Capture Permit",
            icon_url=_SCOREBOARD_STAMP,
        )
        embed.set_thumbnail(url=user.avatar.url)
        embed.description = f"""
        Total Frogs Captured: **`{user_frog_cnt}`**

        **__Inventory__**
        Frogs (Seasonal): **`{user_frog_inv}`**
        Frogs (Frozen): **`0`**

        You currently the `{utility.ordinal(trunc(percentile))}` percentile of all members!
        ```py\n{scoreboard_s}```
        """

        embed.color = discord.Color.from_str("#a2dcf7")

        return embed

    @commands.has_permissions(administrator=True)
    @frog.command(name="register")
    async def frog_register(
        self,
        ctx: commands.Context,
        interval: str,
        persist: str = "30",
        fuzzy: float = 0.5,
        channel: discord.TextChannel = None,
    ):
        """Register this channel as a channel that can spawn frogs.

        If the channel already exists, it will overwrite the settings.

        Interval uses natural duration processing, at least 1 frog every interval.
        Persist is in seconds, how many seconds a frog stays until disappearing.
        Fuzzy is a decimal percent, the randomness of spawning intervals.
        """
        now = pendulum.now()

        if channel is None:
            channel = ctx.channel

        cid = channel.id
        gid = ctx.guild.id

        try:
            interval = parse_duration(interval).in_seconds()
        except InvalidTimeError as err:
            msg = f"Interval {interval} is not a valid time."
            raise commands.BadArgument(msg) from err

        if not self.bot.debug and interval < 60:
            msg = "Inverval must be greater than 60 seconds."
            raise commands.BadArgument(msg)

        try:
            persist = parse_duration(persist).in_seconds()
        except InvalidTimeError as err:
            msg = f"Persist {persist} is not a valid time."
            raise commands.BadArgument(msg) from err

        if not self.bot.debug and (persist < 3 or persist > 120):
            msg = "Persist must be between 3 and 120 seconds."
            raise commands.BadArgument(msg)

        if not self.bot.debug and (fuzzy < 0 or fuzzy > 1):
            msg = "Fuzzy must be between 0 and 1."
            raise commands.BadArgument(msg)
        # End argument checking

        # Update per-guild frog settngs.
        fg = db.table.FrogSpawn(gid, cid, interval, persist, fuzzy)
        await db.frog_spawn.upsert(self.bot.pool, fg)

        # Now we need to update any ongoing tasks, and if not, create it.
        # Not only do we need to reroll run_at, but we need to update payload.
        enabled = await db.frog.get_enabled(self.bot.pool, gid)
        if enabled:
            payload = self.generate_payload(gid, cid, interval, persist, fuzzy)
            record = await db.task.get_one(
                self.bot.pool,
                payload={"gid": gid, "cid": cid},
                tag=["frog"],
            )

            if record is not None:  # If a task already exists
                id = record["id"]
                run_at = frog_factory.roll_future_frog(now, interval, fuzzy)

                # payload = self.bot.json_encoder.encode(payload)
                await db.task.frog_update(self.bot.pool, id, run_at, payload)
            else:  # If task not already exists
                await frog_factory.add_frog_task(self.bot, payload)

        await ctx.message.add_reaction("👍")

    @commands.has_permissions(administrator=True)
    @frog.command(name="clear")
    async def frog_clear(self, ctx: commands.Context):
        """Remove all frog settings for this guild.

        Also stops frog tasks for this guild.
        """
        gid = ctx.guild.id
        await db.frog_spawn.clear(self.bot.pool, gid)
        await db.task.drop(self.bot.pool, tag=["frog"], payload={"gid": gid})
        await ctx.message.add_reaction("👍")

    @frog.command(name="consume")
    async def frog_consume(
        self,
        ctx: commands.Context,
        amount: PositiveInt = 1,
        frog_type: db.table.FrogTypeEnum = db.table.FrogTypeEnum.NORMAL,
    ):
        if amount < 1:
            msg = "Amount of frogs consume must be greater than 0."
            raise commands.BadArgument(msg)

        gid = ctx.guild.id
        uid = ctx.author.id

        member_frogs = await db.member_frog.get_frogs(
            self.bot.pool, gid, uid, frog_type
        )
        if member_frogs is not None and member_frogs - amount < 0:
            msg = f"Member does not have enough frogs ({member_frogs}) to consume."
            raise commands.BadArgument(msg)

        # User confirmation
        wait_for = 120
        fg_type = frog_type.value
        exp_per = _ExpFrog[frog_type.name].value
        total_exp = exp_per * amount

        frogs_old = await db.member_frog.get_frogs(self.bot.pool, gid, uid, frog_type)
        frogs_new = frogs_old - amount

        now = pendulum.now()
        exp_old = await db.member_exp_log.get_seasonal_by_month(
            self.bot.pool, gid, uid, now.year, now.month
        )
        exp_new = exp_old + total_exp

        desc = (
            f"You are about to consume **`{amount}` {fg_type} frog(s)**.\n\n"
            f"These types of frogs grant `{exp_per}` exp per frog, for a total of **`{total_exp}`**.\n\n"
            "Resulting frogs\n"
            f"**`{frogs_old}`** -> **`{frogs_new}`**\n"
            "Resulting exp\n**`"
            f"{exp_old:,}`** -> **`{exp_new:,}`**\n\n"
            "Please confirm."
        )

        embed = utility.prepare_embed("**Confirmation**", desc)
        embed.set_thumbnail(url="https://i.imgur.com/ybxI7pu.png")
        msg: discord.Message = await ctx.send(embed=embed, delete_after=wait_for)
        await msg.add_reaction("❌")
        await msg.add_reaction("✅")

        try:

            def check(reaction, user):
                if (
                    user.id == uid
                    and reaction.message.id == msg.id
                    and reaction.emoji in ["✅", "❌"]
                ):
                    return True
                return False

            reaction, consumer = await self.bot.wait_for(
                "reaction_add", check=check, timeout=wait_for
            )

            if reaction == "❌":
                await msg.delete()
                return

            # Now consume
            now = pendulum.now()

            exp_payload = db.table.MemberExpLog(
                gid, uid, exp_per, now, db.table.MemberExpLogSourceEnum.FROG
            )
            await db.member_exp_log.add(self.bot.pool, exp_payload)

            await db.member_frog.modify_frog(
                self.bot.pool, gid, uid, modify=-amount, frog_type=frog_type
            )

            embed_post = utility.prepare_embed(
                "Frog(s) have been consumed!",
                f"Resulting {fg_type} frogs\n**`{frogs_old}`** -> **`{frogs_new}`**",
            )
            embed_post.set_thumbnail(url="https://i.imgur.com/kCHjymJ.png")
            await msg.edit(embed=embed_post)

        except TimeoutError:
            await msg.delete()

    @frog.group(name="set")
    @commands.has_permissions(administrator=True)
    async def frog_set(self, ctx):
        pass

    @frog_set.command(name="message", aliases=["msg"])
    async def frog_set_message(self, ctx: commands.Context, *, message: str):
        decoded = await user_json.verify(self.bot, ctx, message)

        gid = ctx.guild.id
        await db.frog.set_message(self.bot.pool, gid, decoded)

    @frog_set.command(name="enabled", aliases=["on"])
    async def frog_set_enabled(self, ctx: commands.Context, val: bool):
        """Set frog spawns to true or false.

        Also handles clearing or queuing frog tasks for this guild.
        """
        gid = ctx.guild.id
        await db.frog.set_enabled(self.bot.pool, gid, val)
        if val:
            await frog_factory.reset_guild_frog_tasks(self.bot, gid)
        else:
            await frog_factory.clear_guild_frog_task(self.bot, gid)

    @commands.has_permissions(administrator=True)
    @frog.command(name="demo")
    async def frog_demo(self, ctx: commands.Context):
        gid = ctx.guild.id
        payload = await db.frog.get_message(self.bot.pool, gid)
        decoded = payload

        member = ctx.author
        utility.deep_map(decoded, frog.formatter, member=member)

        content, embed, embeds = user_json.prepare(decoded)
        await ctx.send(content, embed=embed, embeds=embeds)

    @commands.has_permissions(administrator=True)
    @frog.command(name="raw")
    async def frog_raw(self, ctx: commands.Context):
        gid = ctx.guild.id
        payload = await db.frog.get_message(self.bot.pool, gid)
        await ctx.send(f"```{json.dumps(payload)}```")

    def generate_payload(
        self, gid: int, cid: int, interval: int, persist: int, fuzzy: float
    ) -> dict | str:
        return {
            "gid": gid,
            "cid": cid,
            "interval": interval,
            "persist": persist,
            "fuzzy": fuzzy,
        }

    @frog.command(name="spawn")
    @commands.is_owner()
    async def frog_spawn(self, ctx: commands.Context):
        await frog_factory.spawn_and_wait(self.bot, 30, ctx=ctx)

    @frog.command(name="resync")
    @commands.is_owner()
    @utility.author_confirm()
    async def frog_resync(self, ctx: commands.Context):
        _log.warning(f"{ctx.author} called for resync of member frog captures")

        msg = await ctx.send("Starting frog sync...")
        await db.member_frog.sync_with_frog_logs(self.bot.pool)
        await msg.edit(content="Synced! ✅")


async def setup(bot: commands.Bot):
    await bot.add_cog(Frog(bot))
