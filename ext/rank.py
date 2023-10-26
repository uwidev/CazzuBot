"""Per-guild ranked roles based on levels.

Remember that levels also based on experience.
"""
import json
import logging
from typing import TYPE_CHECKING

import discord
from asyncpg import Record
from discord.ext import commands
from discord.ext.commands.context import Context

from src import db, utility


if TYPE_CHECKING:
    from main import CazzuBot


_log = logging.getLogger(__name__)


class Ranks(commands.Cog):
    def __init__(self, bot):
        self.bot: CazzuBot = bot

    async def cog_check(self, ctx: Context) -> bool:
        perms = ctx.channel.permissions_for(ctx.author)
        return any([perms.administrator])

    @commands.group(alias="ranks")
    async def rank(self, ctx: Context):
        pass

    @rank.command(name="add")
    async def rank_add(self, ctx: Context, level: int, role: discord.Role):
        """Add the rank into the guild's settings at said threshold."""
        if level <= 0 or level > 999:
            msg = "Level must be between 1-999."
            await ctx.send(msg)
            return

        gid = ctx.guild.id
        rid = role.id
        await db.rank_threshold.add(
            self.bot.pool, db.table.RankThreshold(gid, rid, level)
        )

    @rank.command(name="remove", aliases=["del"])
    async def rank_remove(self, ctx: Context, role: discord.Role):
        """Remove the rank from the guild by role.

        Later implementation could do by role OR threshold.
        """
        gid = ctx.guild.id
        rid = role.id
        await db.rank_threshold.delete(self.bot.pool, gid, rid)

    # @author_confirm()
    @rank.command(name="clear", aliases=["purge", "drop"])
    async def rank_clear(self, ctx: Context):
        gid = ctx.guild.id
        await db.rank_threshold.drop(self.bot.pool, gid)

    @rank.group(name="set")
    async def rank_set(self, ctx):
        pass

    @rank_set.command(name="message", aliases=["msg"])
    async def rank_set_message(self, ctx: commands.Context, *, message):
        decoded = await utility.verify_json(
            self.bot, ctx, message, self._formatter, member=ctx.author
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
        utility.deep_map(decoded, self._formatter, member=member)

        content, embed, embeds = utility.prepare_message(decoded)
        await ctx.send(content, embed=embed, embeds=embeds)

    def _formatter(self, s: str, *, member, old_rank=None, new_rank=None):
        """Format string with rank-related placeholders.

        {avatar}
        {name} -> display_name
        {mention}
        {id}
        {old} -> previous rank
        {new} -> new rank
        """
        return s.format(
            avatar=member.avatar.url,
            name=member.display_name,
            mention=member.mention,
            id=member.id,
            old=old_rank,
            new=new_rank,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Ranks(bot))
