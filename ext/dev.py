"""Developer commands for sandbox purposes."""
import logging

import pendulum
from discord.ext import commands

import src.db_interface as dbi
import src.db_schema


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
    async def test(self, ctx: commands.Context):
        await dbi.initialize_guild(self.bot.pool, ctx.guild.id)

    # @commands.command()
    # async def upgrade(self, ctx: commands.Context):
    #     dbi.upgrade(self.bot.pool)

    # @commands.command()
    # async def get(self, ctx: commands.Context):
    #     res = dbi.get_by_id(self.bot.pool, Table.GUILD_SETTINGS, ctx.guild.id)
    #     _log.warning(res)


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
