'''
Developer commands for sandbox purposes
'''
import logging

import discord
from discord.ext import commands

import db_interface_guild as dbi
from utility import author_confirm

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
    async def write_guild(self, ctx: commands.Context):
        dbi.insert_guild(self.bot.db, ctx.guild.id)

    @commands.command()
    @author_confirm('This command will reset **EVERYTHING** for this guild.\n'
                    'Do you wish to continue?')
    async def init_guild(self, ctx: commands.Context):
        dbi.initialize(self.bot.db, ctx.guild.id)

    @commands.command()
    async def upgrade(self, ctx: commands.Context):
        dbi.upgrade(self.bot.db, ctx.guild.id)

    @commands.command()
    async def fetch(self, ctx: commands.Context):
        res = dbi.fetch(self.bot.db, ctx.guild.id)
        _log.info(res)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
