"""Contains the implementation of all things related moderation.

TODO Create customized user group and permissions
"""
import logging

import discord
import pendulum
from discord.ext import commands, tasks
from discord.ext.commands.context import Context

from src import modlog, settings, task
from src.db_templates import (
    ModLogEntry,
    ModLogTaskEntry,
    ModLogType,
)
from src.ntlp import NormalizedTime, NotFutureError, is_future


_log = logging.getLogger(__name__)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log_expired.start()

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
        expires_on: NormalizedTime,
        *,
        reason: str,
    ):
        """Mute the user until the specified time or date.

        Should use relative time when calling, but does accept absolute time/dates. If
        absolute time/date is used, it should be converted to UTC.

        A potential feature would be to allow the user store their timezone to use here.
        """
        now = pendulum.now("UTC")
        if not is_future(now, expires_on):
            raise NotFutureError(expires_on)

        log_id = await modlog.get_unique_id(self.bot.db, ctx.guild.id)

        log = ModLogEntry(
            member.id,
            ctx.guild.id,
            log_id,
            ModLogType.MUTE,
            now,
            expires_on,
            reason,
            # ModLogStatus.PARDONED,
        )
        tsk = ModLogTaskEntry(
            "modlog",
            expires_on,
            ctx.guild.id,
            member.id,
            ModLogType.MUTE,
        )

        await modlog.add(self.bot.db, log)
        await task.add(self.bot.db, tsk)  # Add to task to handle

        _log.warning("Mute currently does not actually mute!")

    @tasks.loop(seconds=60.0)
    async def log_expired(self):
        now = pendulum.now(tz="UTC")
        modlog_tasks = await task.tag(self.bot.db, "modlog")
        expired_logs = list(filter(lambda t: t["run_at"] < now, modlog_tasks))

        for log in expired_logs:
            log_type: ModLogType = log["log_type"]
            uid: int = log["uid"]
            _log.info(
                "%s's has %s expired, reverting infraction actions...",
                uid,
                log_type.value,
            )
            _log.warning("ModLog resolution has not yet been implemented!")

    @log_expired.before_loop
    async def before_log_expired(self):
        await self.bot.wait_until_ready()

    @commands.group()
    async def set(self, ctx: Context):
        pass

    @set.command(name="mute")
    async def set_mute(self, ctx: Context, *, role: discord.Role):
        to_set = settings.Settings(
            "mute_role",
            {"id": role.id},
        )

        await settings.write(self.bot.db, ctx.guild.id, to_set)


async def setup(bot: commands.Bot):
    """Set up this extension for the bot.

    Default settings for this extension must be defined here.
    Format should be as follows.
    Setting()
    """
    mod_settings = settings.Settings("mute_role", {"id": None})

    default_mod_settings = settings.Guild({"mod": {}})
    default_mod_settings.mod = mod_settings

    bot.guild_defaults.update(default_mod_settings)

    await bot.add_cog(Moderation(bot))
