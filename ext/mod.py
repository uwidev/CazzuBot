"""Contains the implementation of all things related moderation.

TODO Create customized user group and permissions
"""
import json
import logging
from datetime import timezone

import discord
import pendulum
from discord.ext import commands, tasks
from discord.ext.commands.context import Context

import src.db_interface as dbi
from src import modlog, settings, task
from src.db_schema import Modlog, ModlogStatusEnum, ModlogTypeEnum, Task
from src.ntlp import NormalizedTime, NotFutureError, is_future


_log = logging.getLogger(__name__)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.log_expired.start()

    def cog_check(self, ctx: Context) -> bool:
        """Check to make sure user satisfies 'moderation' permission.

        Currently checks for kick or ban perms, but eventually we want to designate
        a specific role in the database to as moderator. Potentially expanding to
        specific users as well, dependinng on on how advance permission management is.
        """
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

        log_id = 0  # NEED TO IMPLEMENT GET LATEST CASE ID

        log = Modlog(
            ctx.guild.id, member.id, log_id, ModlogTypeEnum.MUTE, now, expires_on
        )
        payload = {
            "gid": ctx.guild.id,
            "uid": member.id,
            "log_type": ModlogTypeEnum.MUTE.value,
        }
        tsk = Task(["modlog"], expires_on, json.dumps(payload))

        await modlog.add(self.bot.pool, log)
        await task.add(self.bot.pool, tsk)  # Add to task to handle

        _log.warning("Mute currently does not actually mute!")

    @tasks.loop(seconds=60.0)
    async def log_expired(self):
        """Handle mute and temp-ban expirations."""
        now = pendulum.now(tz="UTC")
        modlog_tasks = await task.tag(self.bot.pool, "modlog")
        expired_logs = list(filter(lambda t: t[1] < now, modlog_tasks))

        for log in expired_logs:
            payload_raw = log[2]
            payload = json.loads(payload_raw)
            log_type = ModlogTypeEnum(payload["log_type"])
            uid: int = payload["uid"]
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
        await dbi.set_mute_role(self.bot.pool, ctx.guild.id, role.id)


async def setup(bot: commands.Bot):
    """Set up this extension for the bot.

    Default settings for this extension must be defined here.
    Format should be as follows.
    Setting()
    """
    # mod_settings = settings.Settings("mute_role", {"id": None})

    # default_mod_settings = settings.Guild({"mod": {}})
    # default_mod_settings.mod = mod_settings

    # bot.guild_defaults.update(default_mod_settings)

    await bot.add_cog(Moderation(bot))
