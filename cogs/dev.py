"""
Developer commands for sandbox purposes
"""
import logging

import discord
from discord.ext import commands

import db_interface as dbi
from db_interface import Table
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
    async def write(self, ctx: commands.Context):
        dbi.insert(self.bot.db, Table.GUILD_SETTINGS, ctx.guild.id)
        dbi.insert(self.bot.db, Table.GUILD_MODLOGS, ctx.guild.id)

    @commands.command()
    async def init(self, ctx: commands.Context):
        dbi.initialize(self.bot.db, Table.GUILD_SETTINGS, ctx.guild.id)

    @commands.command()
    async def upgrade(self, ctx: commands.Context):
        dbi.upgrade(self.bot.db)

    @commands.command()
    async def get(self, ctx: commands.Context):
        res = dbi.get(self.bot.db, Table.GUILD_SETTINGS, ctx.guild.id)
        _log.warning(res)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
