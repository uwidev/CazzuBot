"""Contains the impplementation of levels systems.

A user's level is derived from a user's experience points. Because of this, levels do
not actually need to be stored internally.
"""

import logging

import discord
from discord.ext import commands

from src import db, utility
from src.cazzubot import CazzuBot


_log = logging.getLogger(__name__)

# from src import level, level_helper


class Level(commands.Cog):
    def __init__(self, bot: CazzuBot):
        self.bot = bot

    @commands.group(name="level", aliases=["lvl"])
    async def level(self, ctx: commands.Context):
        pass

    @level.group(name="set")
    async def level_set(self, ctx):
        pass

    @level_set.command(name="message", aliases=["msg"])
    async def level_set_message(self, ctx: commands.Context, *, message):
        decoded = await utility.verify_json(
            self.bot, ctx, message, self._formatter, member=ctx.author
        )

        gid = ctx.guild.id
        await db.level.set_message(
            self.bot.pool, gid, self.bot.json_encoder.encode(decoded)
        )

    @level.command(name="demo")
    async def level_demo(self, ctx: commands.Context):
        gid = ctx.guild.id
        payload = await db.level.get_message(self.bot.pool, gid)
        decoded = self.bot.json_decoder.decode(payload)

        member = ctx.author
        utility.deep_map(decoded, self._formatter, member=member)

        content, embed, embeds = utility.prepare_message(decoded)
        await ctx.send(content, embed=embed, embeds=embeds)

    def _formatter(self, s: str, *, member, old_level=None, new_level=None):
        """Format string with rank-related placeholders.

        {avatar}
        {name} -> display_name
        {mention}
        {id}
        {old} -> previous level
        {new} -> new level
        """
        return s.format(
            avatar=member.avatar.url,
            name=member.display_name,
            mention=member.mention,
            id=member.id,
            old=old_level,
            new=new_level,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Level(bot))
