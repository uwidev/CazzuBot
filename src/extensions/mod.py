"""Contains the implementation of all things related moderation.

TODO Create customized user group and permissions
"""
import logging

import discord
import pendulum
from discord.ext import commands, tasks
from discord.ext.commands.context import Context
from discord.utils import format_dt
from pytz import timezone

import src.db_aggregator as dsa
import src.db_interface as dbi
from src.db_aggregator import Scope, Table
from src.future_time import FutureTime, NotFutureError, is_future
from src.modlog import LogType, ModLog, get_next_case_id


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
        expires_at: FutureTime,
        *,
        reason: str,
    ):
        """Mute the user until the specified time or date.

        Should use relative time when calling, but does accept absolute time/dates. If
        absolute time/date is used, it should be converted to UTC.

        A potential feature would be to allow the user store their timezone to use here.
        """
        now = pendulum.now(timezone("UTC"))
        if not is_future(now, expires_at):
            raise NotFutureError(expires_at)

        case_id = get_next_case_id(self.bot.db, ctx.guild.id)

        user_log = ModLog(
            member.id, ctx.guild.id, case_id, LogType.MUTE, now, expires_at, reason
        )
        _log.info(str(user_log.__dict__))
        await ctx.send(
            f"Muted on: {format_dt(pendulum.now())}\n"
            f"Expires on: {format_dt(expires_at.astimezone(timezone('US/Pacific')))}"
        )

        dbi.insert_document(self.bot.db, "MODLOG", user_log.as_dict())

    @tasks.loop(minutes=1)
    async def case_expired(self):
        pass


async def setup(bot: commands.Bot):
    dsa.register_settings(Table.GUILD_SETTINGS, Scope.DEFAULT, settings)
    await bot.add_cog(Moderation(bot))
