"""Developer commands for sandbox purposes."""
import logging

import pendulum
from discord.ext import commands

import src.db.schema
from src import db
from src.db import modlog
from src.db.guild import add_guild


# import src.db_interface as dbi
# from src.serializers import TestEnum


_log = logging.getLogger(__name__)


class Dev(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def cog_check(self, ctx):
        return ctx.author.id == self.bot.owner_id

    @commands.command()
    async def owner(self, ctx):
        _log.info("%s is the bot owner.", ctx.author)

    @commands.command()
    async def init(self, ctx):
        await add_guild(self.bot.pool, db.GuildSchema(ctx.guild.id))

    @commands.command()
    async def test(self, ctx: commands.Context):
        pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
