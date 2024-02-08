"""Contains the impplementation of levels systems.

A user's level is derived from a user's experience points. Because of this, levels do
not actually need to be stored internally.
"""

import logging

import discord
from discord.ext import commands

from src import db, level, user_json, utility
from src.cazzubot import CazzuBot


_log = logging.getLogger(__name__)

# from src import level, level_helper


class Level(commands.Cog):
    def __init__(self, bot: CazzuBot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        perms = ctx.channel.permissions_for(ctx.author)
        return any([perms.administrator])

    @commands.group(name="level", aliases=["lvl"])
    async def level(self, ctx: commands.Context):
        pass

    @level.group(name="set")
    async def level_set(self, ctx):
        pass

    @level_set.command(name="message", aliases=["msg"])
    async def level_set_message(self, ctx: commands.Context, *, message):
        decoded = await user_json.verify(
            self.bot, ctx, message, level.formatter, member=ctx.author
        )

        gid = ctx.guild.id
        await db.level.set_message(self.bot.pool, gid, decoded)

    @level.command(name="demo")
    async def level_demo(self, ctx: commands.Context):
        gid = ctx.guild.id
        payload = await db.level.get_message(self.bot.pool, gid)
        decoded = payload

        member = ctx.author
        utility.deep_map(decoded, level.formatter, member=member)

        content, embed, embeds = user_json.prepare(decoded)
        await ctx.send(content, embed=embed, embeds=embeds)


async def setup(bot: commands.Bot):
    await bot.add_cog(Level(bot))
