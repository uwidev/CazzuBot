"""Per-guild ranked roles based on levels.

Remember that levels also based on experience.
"""
import json
import logging
from typing import TYPE_CHECKING

import discord
from asyncpg import Record
from discord.ext import commands

from src import db, rank, user_json, utility
from src.db.table import WindowEnum


if TYPE_CHECKING:
    from main import CazzuBot


_log = logging.getLogger(__name__)


class Ranks(commands.Cog):
    def __init__(self, bot):
        self.bot: CazzuBot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        perms = ctx.channel.permissions_for(ctx.author)
        return any([perms.administrator])

    @commands.group(alias="ranks")
    async def rank(self, ctx: commands.Context):
        pass

    @rank.command(name="add")
    async def rank_add(
        self,
        ctx: commands.Context,
        level: int,
        role: discord.Role,
        mode: WindowEnum = WindowEnum.SEASONAL,
    ):
        """Add the rank into the guild's settings at said threshold."""
        if level <= 0 or level > 999:
            msg = "Level must be between 1-999."
            await ctx.send(msg)
            return

        gid = ctx.guild.id
        rid = role.id
        await db.rank_threshold.add(
            self.bot.pool, db.table.RankThreshold(gid, rid, level, mode)
        )

        await ctx.message.add_reaction("👍")

    @rank.command(name="remove", aliases=["del"])
    async def rank_remove(
        self,
        ctx: commands.Context,
        arg: discord.Role | int,
        mode: WindowEnum = WindowEnum.SEASONAL,
    ):
        """Remove the rank from the guild by role or level."""
        gid = ctx.guild.id
        payload = arg if isinstance(arg, int) else arg.id
        await db.rank_threshold.delete(self.bot.pool, gid, payload, mode)

    @rank.command(name="clean")
    async def rank_clean(self, ctx: commands.Context):
        """Remove ranks which can no longer be referenced because they were deleted."""
        gid = ctx.guild.id
        payload = await db.rank_threshold.get(self.bot.pool, gid)
        rank_ids = [p.get("rid") for p in payload]
        roles = [ctx.guild.get_role(rid) for rid in rank_ids]
        removed_rids = [rank_ids[i] for i in range(len(roles)) if not roles[i]]
        await db.rank_threshold.batch_delete(self.bot.pool, gid, removed_rids)

    # @author_confirm()
    @rank.command(
        name="clear",
        aliases=["purge", "drop"],
    )
    async def rank_clear(
        self,
        ctx: commands.Context,
        mode: WindowEnum = WindowEnum.SEASONAL,
    ):
        gid = ctx.guild.id
        await db.rank_threshold.drop(self.bot.pool, gid, mode)

    @rank.group(name="set")
    async def rank_set(self, ctx):
        pass

    @rank_set.command(name="enabled")
    async def rank_set_enabled(self, ctx: commands.Context, val: bool):
        gid = ctx.guild.id
        await db.rank.set_enabled(self.bot.pool, gid, val)

    @rank_set.command(name="keepOld")
    async def rank_set_keep_old(self, ctx: commands.Context, val: bool):
        gid = ctx.guild.id
        await db.rank.set_keep_old(self.bot.pool, gid, val)

    @rank_set.command(name="message", aliases=["msg"])
    async def rank_set_message(self, ctx: commands.Context, *, message):
        decoded = await user_json.verify(
            self.bot, ctx, message, rank.formatter, member=ctx.author
        )

        gid = ctx.guild.id
        await db.rank.set_message(
            self.bot.pool, gid, self.bot.json_encoder.encode(decoded)
        )

    @rank.command(name="demo")
    async def rank_demo(self, ctx: commands.Context):
        gid = ctx.guild.id
        payload = await db.rank.get_message(self.bot.pool, gid)
        decoded = self.bot.json_decoder.decode(payload)

        member = ctx.author
        utility.deep_map(decoded, rank.formatter, member=member)

        content, embed, embeds = user_json.prepare(decoded)
        await ctx.send(content, embed=embed, embeds=embeds)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ranks(bot))
