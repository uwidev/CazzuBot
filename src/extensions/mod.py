"""Contains the implementation of all things related moderation.

TODO Create customized user group and permissions
"""
import logging

import discord
from discord.ext import commands
from discord.ext.commands.context import Context

import src.db_settings_aggregator as dsa
from src.db_settings_aggregator import Scope, Table
from src.future_time import FutureTime
from src.modlog import LogType, ModLog


_log = logging.getLogger(__name__)


settings = {}


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def cog_check(self, ctx: Context) -> bool:
        perms = ctx.channel.permissions_for(ctx.author)
        return any([perms.moderate_members, perms.kick_members, perms.ban_members])

    @commands.command()
    async def mod_check(self, ctx: Context):
        await ctx.send("You have moderator permissions!")

    @commands.command()
    async def warn(self, ctx: Context, member: discord.Member, reason: str):
        _log.info("Member %s was warned: %s", member.name, reason)

    @commands.command()
    async def mute(
        self,
        ctx: Context,
        member: discord.Member,
        until: FutureTime,
        *,
        reason: str,
    ):
        """Mute the user until the specified time or date.

        Should use relative time when calling, but does accept absolute time/dates. If
        absolute time/date is used, it should be converted to UTC.

        A potential feature would be to allow the user store their timezone to use here.
        """
        user_log = ModLog(member.id, LogType.MUTE, until, reason)
        _log.info(str(user_log.__dict__))


async def setup(bot: commands.Bot):
    dsa.register_settings(Table.GUILD_SETTINGS, Scope.DEFAULT, settings)
    await bot.add_cog(Moderation(bot))
