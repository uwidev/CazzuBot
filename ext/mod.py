"""Contains the implementation of all things related moderation.

TODO Create customized user group and permissions
"""
import logging

import discord
import pendulum
from discord.ext import commands, tasks
from discord.ext.commands.context import Context

import src.db_interface as dbi
from src.db_templates import (
    GuildSetting,
    GuildSettingScope,
    ModLogEntry,
    ModLogTaskEntry,
    ModLogType,
    ModSettingName,
    mod_defaults,
)
from src.future_time import FutureTime, NotFutureError, is_future
from src.modlog import add_modlog, get_next_log_id
from src.settings_aggregator import register_settings
from src.task_manager import get_tasks


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
        expires_on: FutureTime,
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

        log_id = await get_next_log_id(self.bot.db, ctx.guild.id)

        modlog = ModLogEntry(
            member.id,
            ctx.guild.id,
            log_id,
            ModLogType.MUTE,
            now,
            expires_on,
            reason,
            # ModLogStatus.PARDONED,
        )
        ModLogTaskEntry(ctx.guild.id, member.id, ModLogType.MUTE, expires_on)

        await add_modlog(self.bot.db, modlog)
        # await add_task(self.bot.db, task)  # Add to task to handle

        _log.warning("Mute currently does not actually mute!")

    @tasks.loop(seconds=30.0)
    async def log_expired(self):
        now = pendulum.now(tz="UTC")
        modlog_tasks = await get_tasks(self.bot.db)

        expired_logs = filter(lambda t: t["expires_on"] < now, modlog_tasks)
        for log in expired_logs:
            log_type: ModLogType = log["log_type"]
            uid: int = log["uid"]
            _log.info(
                "%s's has %s expired, reverting infraction actions...",
                uid,
                log_type.value,
            )
            _log.warning("ModLog resolution has not yet been implemented!")

    @commands.group()
    async def set(self, ctx):
        pass

    @set.command(name="mute")
    async def set_mute(self, ctx, role: discord.Role):
        setting = GuildSetting(
            ctx.guild.id,
            ModSettingName.MUTE_ROLE,
            role.id,
            GuildSettingScope.GUILD,
        )

        await dbi.insert_document(
            self.bot.db,
            dbi.Table.GUILD_SETTING.name,
            setting,
        )


async def setup(bot: commands.Bot):
    register_settings(mod_defaults)
    await bot.add_cog(Moderation(bot))
