"""Contains the implementation of all things related moderation.

TODO Create customized user group and permissions
"""
import logging
from typing import TYPE_CHECKING

import discord
import pendulum
from discord.ext import commands, tasks
from discord.ext.commands.context import Context

from src import db
from src.db.table import Modlog, ModlogTypeEnum, Task
from src.ntlp import (
    InvalidTimeError,
    NotFutureError,
    is_future,
    normalize_time_str,
)


if TYPE_CHECKING:  # magical?? shit that helps with type checking
    from main import CazzuBot


_log = logging.getLogger(__name__)


class Moderation(commands.Cog):
    def __init__(self, bot):
        self.bot: CazzuBot = bot
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
        """Warn the member, creating a modlog and adding it to database."""
        now = pendulum.now("UTC")

        log = Modlog(
            ctx.guild.id, member.id, 0, ModlogTypeEnum.WARN, now, reason=reason
        )

        await db.modlog.add(self.bot.pool, log)

    @commands.command()
    @db.guild.req_mute_id()
    async def mute(
        self,
        ctx: Context,
        member: discord.Member,
        *,
        raw: str = None,
    ):
        """Mute the user until the specified time or date.

        Should use relative time when calling, but does accept absolute time/dates. Do
        note that time is parsed as UTC.

        A potential feature would be to allow the user store their timezone to use here.
        """
        now = pendulum.now("UTC")

        duration, reason = self.prase_dur_str_mix(raw)

        if duration and not is_future(now, duration):
            raise NotFutureError(duration)

        # cid is 0 because cid is serialized per-guild
        log = Modlog(
            ctx.guild.id,
            member.id,
            0,
            ModlogTypeEnum.MUTE,
            now,
            duration,
            reason,
        )

        await db.modlog.add(self.bot.pool, log)

        # Add to task to handle in future
        if duration:
            raw = {
                "gid": ctx.guild.id,
                "uid": member.id,
                "log_type": ModlogTypeEnum.MUTE,
            }
            tsk = Task(
                ["modlog"],
                duration,
                self.bot.json_encoder.encode(raw),
            )

            await db.task.add(self.bot.pool, tsk)

        # Actually mute here
        mute_id = await db.guild.get_mute_id(self.bot.pool, ctx.guild.id)
        mute_role = ctx.guild.get_role(mute_id)
        await member.add_roles(mute_role, reason=reason)

    @commands.command()
    async def kick(
        self,
        ctx: Context,
        member: discord.Member,
        *,
        reason: str = None,
    ):
        """Kick a member from the guild, write reason and stuff to database."""
        now = pendulum.now("UTC")

        # cid is 0 because cid is serialized per-guild
        log = Modlog(
            ctx.guild.id,
            member.id,
            0,
            ModlogTypeEnum.KICK,
            now,
            reason=reason,
        )

        await db.modlog.add(self.bot.pool, log)

        # Actually ban here
        await member.kick(reason=reason)

    @commands.command()
    async def ban(
        self,
        ctx: Context,
        member: discord.Member,
        *,
        raw: str = None,
    ):
        """Bans the user until the specified time or date. If not provided, forever.

        Should use relative time when calling, but does accept absolute time/dates. Do
        note that time is parsed as UTC.

        A potential feature would be to allow the user store their timezone to use here.
        """
        now = pendulum.now("UTC")

        duration, reason = self.prase_dur_str_mix(raw)

        if duration and not is_future(now, duration):
            raise NotFutureError(duration)

        ban_type = ModlogTypeEnum.TEMPBAN if duration else ModlogTypeEnum.BAN

        # cid is 0 because cid is serialized per-guild
        log = Modlog(
            ctx.guild.id,
            member.id,
            0,
            ban_type,
            now,
            duration,
            reason,
        )

        await db.modlog.add(self.bot.pool, log)

        # Add to task to handle in future
        if duration:
            raw = {
                "gid": ctx.guild.id,
                "uid": member.id,
                "log_type": ban_type,
            }
            tsk = Task(
                ["modlog"],
                duration,
                self.bot.json_encoder.encode(raw),
            )

            await db.task.add(self.bot.pool, tsk)

        # Actually ban here
        await member.ban(reason=reason)

    @tasks.loop(seconds=5.0)
    async def log_expired(self):
        """Handle mute and temp-ban expirations."""
        now = pendulum.now(tz="UTC")
        modlog_tasks = await db.task.get(self.bot.pool, "modlog")
        expired_logs = list(filter(lambda t: t[1] < now, modlog_tasks))

        for log in expired_logs:
            payload_raw = log[2]
            payload = self.bot.json_decoder.decode(payload_raw)
            log_type = ModlogTypeEnum(payload["log_type"])
            uid: int = payload["uid"]
            gid: int = payload["gid"]

            if log_type == ModlogTypeEnum.MUTE:
                guild = self.bot.get_guild(gid)
                mute_id = await db.guild.get_mute_id(self.bot.pool, gid)
                mute_role = guild.get_role(mute_id)

                member = await guild.fetch_member(uid)
                await member.remove_roles(mute_role, reason="Mute expired.")
                await db.task.drop(self.bot.pool, log["id"])

                _log.info(
                    "%s's has %s expired, reverting infraction actions...",
                    uid,
                    log_type.value,
                )

            if log_type == ModlogTypeEnum.TEMPBAN:
                guild = self.bot.get_guild(gid)
                user = await self.bot.fetch_user(uid)
                await guild.unban(user, reason="Tempban expired.")
                await db.task.drop(self.bot.pool, log["id"])

                _log.info(
                    "%s's has %s expired, reverting infraction actions...",
                    uid,
                    log_type.value,
                )

            # _log.warning("ModLog resolution has not yet been implemented!")

    @log_expired.before_loop
    async def before_log_expired(self):
        await self.bot.wait_until_ready()

    @commands.group()
    async def set(self, ctx: Context):
        pass

    @set.command(name="mute")
    async def set_mute(self, ctx: Context, *, role: discord.Role):
        await db.guild.set_mute_id(self.bot.pool, ctx.guild.id, role.id)

    def prase_dur_str_mix(self, raw) -> tuple[pendulum.DateTime, str]:
        """Transform a time string mix.

        Time is optional, and must come first.

        ==== Examples of expected output =====
        DateTime dur 2h, "foo bar barz"         "2h foo bar barz"
        None, "foo bar barz"                    "2h foo bar barz"
        None, "foo 2h bar barz"                 "foo 2h bar barz"
        """
        time = None
        s = raw
        if raw:
            if raw.find(" ") != -1:
                dur_raw, s = raw.split(" ", 1)
            else:
                dur_raw = raw
            try:
                time = normalize_time_str(dur_raw)
            except InvalidTimeError:
                s = raw

        return time, s


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
