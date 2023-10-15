"""Developer commands for sandbox purposes."""
import logging
from typing import TYPE_CHECKING

import pendulum
from discord.ext import commands

from src import db


if TYPE_CHECKING:
    from main import CazzuBot


# import src.db_interface as dbi
# from src.serializers import TestEnum


_log = logging.getLogger(__name__)


class Dev(commands.Cog):
    def __init__(self, bot):
        self.bot: CazzuBot = bot

    def cog_check(self, ctx):
        return ctx.author.id == self.bot.owner_id

    @commands.command()
    async def test(self, ctx: commands.Context):
        await ctx.reply(ctx.guild.get_member(648965826514518017))


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
