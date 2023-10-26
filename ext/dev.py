"""Developer commands for sandbox purposes."""
import logging
from typing import TYPE_CHECKING

import discord
import pendulum
from asyncstdlib.builtins import list as alist
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
        if ctx.author.id == 338486462519443461:
            ctx.author.edit()

    # @commands.Cog.listener()
    # async def on_member_update(self, before: discord.Member, after: discord.Member):
    #     if before.id == 338486462519443461:
    #         _log.info(f"{before.pending=}")
    #         _log.info(f"{before.flags.started_onboarding=}")
    #         _log.info(f"{before.flags.completed_onboarding=}")
    #         _log.info(f"{after.pending=}")
    #         _log.info(f"{after.flags.started_onboarding=}")
    #         _log.info(f"{after.flags.completed_onboarding=}")


async def setup(bot: commands.Bot):
    await bot.add_cog(Dev(bot))
