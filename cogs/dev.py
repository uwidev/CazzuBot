'''
Developer commands for sandbox purposes
'''
import logging

import discord
from discord.ext import commands

import db_interface_guild as dbi

_log = logging.getLogger(__name__)

class Dev(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def cog_check(self, ctx):
        return ctx.author.id == self.bot.owner_id

    @commands.command()
    async def test(self, ctx):
        _log.info('%s is the bot owner.', ctx.author)

    @commands.command()
    async def write_guild(self, ctx):
        dbi.insert_guild(self.bot.db, ctx.guild.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
