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

from src import db
from src.utility import author_confirm


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

    @rank.command()
    async def add(self, ctx: Context, level: int, role: discord.Role):
        """Add the rank into the guild's settings at said threshold."""
        if level <= 0 or level > 999:
            msg = "Level must be between 1-999."
            await ctx.send(msg)
            return

        gid = ctx.guild.id
        rid = role.id
        await db.rank.add(self.bot.pool, db.table.Rank(gid, rid, level))

    @rank.command(aliases=["del"])
    async def remove(self, ctx: Context, role: discord.Role):
        """Remove the rank from the guild by role.

        Later implementation could do by role OR threshold.
        """
        gid = ctx.guild.id
        rid = role.id
        await db.rank.delete(self.bot.pool, gid, rid)

    @author_confirm()
    @rank.command(aliases=["purge", "drop"])
    async def clear(self, ctx: Context):
        gid = ctx.guild.id
        await db.rank.drop(self.bot.pool, gid)

    async def on_experience_gain(self, ctx: Context, member_db: Record):
        """Check if user's current exp satisfies ranking conditions."""


async def setup(bot: commands.Bot):
    await bot.add_cog(Ranks(bot))
