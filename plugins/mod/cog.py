"""Mod plugin — controller: moderation commands and scheduled expiries.

Single-guild port of v1's ``ext/mod.py``. Mute and temp-ban expirations are
handled by the central scheduler (tag ``modlog``); the due handler lives here
because it is pure discord side effects.
"""

import logging
from typing import Any

import discord
import pendulum
from discord.ext import commands

from cazzubot.bot import CazzuBot
from cazzubot.models import ModlogTypeEnum
from cazzubot.window import window_error, window_info, window_success
from typing_extensions import override

from . import db
from .logic import ensure_future, resolve_ban_type, split_duration_reason

_log = logging.getLogger(__name__)


class ModCog(commands.Cog):
    """Moderation actions with a persistent modlog."""

    def __init__(self, bot: CazzuBot) -> None:
        self.bot = bot

    @override
    async def cog_check(self, ctx: commands.Context[Any]) -> bool:
        author = ctx.author
        if not isinstance(author, discord.Member):
            return False
        perms = ctx.channel.permissions_for(author)
        return any(
            [
                perms.moderate_members,
                perms.kick_members,
                perms.ban_members,
            ]
        )

    @commands.hybrid_command()
    async def mod_check(self, ctx: commands.Context[CazzuBot]) -> None:
        """Check if you have moderator permissions."""
        await ctx.send("You have moderator permissions!")

    @commands.hybrid_command()
    async def warn(
        self,
        ctx: commands.Context[CazzuBot],
        member: discord.Member,
        *,
        reason: str,
    ) -> None:
        """Warn the member, writing a modlog entry."""
        await db.add_log(
            self.bot.db,
            member.id,
            ModlogTypeEnum.WARN,
            pendulum.now("UTC"),
            reason=reason,
        )
        await window_info(ctx, f"Warned {member}")

    @commands.hybrid_command()
    async def mute(
        self,
        ctx: commands.Context[CazzuBot],
        member: discord.Member,
        *,
        raw: str | None = None,
    ) -> None:
        """Mute the user until the given time (relative or absolute, UTC)."""
        mute_id = await db.get_mute_role(self.bot.settings)
        if not mute_id:
            await ctx.send(
                "No mute role has been set (`set mute <role>`)."
            )
            return

        now = pendulum.now("UTC")
        duration, reason = split_duration_reason(raw)
        ensure_future(now, duration)

        await db.add_log(
            self.bot.db,
            member.id,
            ModlogTypeEnum.MUTE,
            now,
            expires_on=duration,
            reason=reason,
        )
        if duration:
            await self.bot.scheduler.add(
                "modlog",
                duration,
                {"uid": member.id, "log_type": ModlogTypeEnum.MUTE.value},
            )

        guild = ctx.guild
        if guild is None:
            await ctx.send("Not in a guild.")
            return
        role = guild.get_role(mute_id)
        if role is None:
            await ctx.send("Mute role no longer exists in this server.")
            return
        await member.add_roles(role, reason=reason)
        await window_info(ctx, f"Muted {member}")

    @commands.hybrid_command()
    async def kick(
        self,
        ctx: commands.Context[CazzuBot],
        member: discord.Member,
        *,
        reason: str | None = None,
    ) -> None:
        """Kick a member, writing a modlog entry."""
        await db.add_log(
            self.bot.db,
            member.id,
            ModlogTypeEnum.KICK,
            pendulum.now("UTC"),
            reason=reason,
        )
        await member.kick(reason=reason)
        await window_info(ctx, f"Kicked {member}")

    @commands.hybrid_command()
    async def ban(
        self,
        ctx: commands.Context[CazzuBot],
        member: discord.Member,
        *,
        raw: str | None = None,
    ) -> None:
        """Ban the user until the given time; without one, forever."""
        now = pendulum.now("UTC")
        duration, reason = split_duration_reason(raw)
        ensure_future(now, duration)

        ban_type = resolve_ban_type(duration)
        await db.add_log(
            self.bot.db,
            member.id,
            ban_type,
            now,
            expires_on=duration,
            reason=reason,
        )
        if duration:
            await self.bot.scheduler.add(
                "modlog",
                duration,
                {"uid": member.id, "log_type": ban_type.value},
            )
        await member.ban(reason=reason)
        await window_info(ctx, f"Banned {member}")

    @commands.hybrid_command()
    async def unmute(
        self, ctx: commands.Context[CazzuBot], member: discord.Member
    ) -> None:
        """Remove the mute role and any pending mute expiry."""
        mute_id = await db.get_mute_role(self.bot.settings)
        guild = ctx.guild
        if guild is None:
            await window_error(ctx, "Run unmute in the server, not DMs.")
            return
        role = guild.get_role(mute_id) if mute_id else None
        if role and role in member.roles:
            await member.remove_roles(role, reason="Unmuted.")
        for task in await self.bot.scheduler.get("modlog"):
            payload = task.payload
            if (
                payload.get("uid") == member.id
                and payload.get("log_type") == "mute"
            ):
                await self.bot.scheduler.drop(task.id)
        await window_info(ctx, f"Unmuted {member}")

    @commands.hybrid_command()
    async def unban(
        self, ctx: commands.Context[CazzuBot], user: discord.User
    ) -> None:
        """Unban a user and drop any pending tempban expiry."""
        guild = ctx.guild
        if guild is None:
            await window_error(ctx, "Run unban in the server, not DMs.")
            return
        await guild.unban(user, reason="Unbanned.")
        for task in await self.bot.scheduler.get("modlog"):
            payload = task.payload
            if (
                payload.get("uid") == user.id
                and payload.get("log_type") == "tempban"
            ):
                await self.bot.scheduler.drop(task.id)
        await window_info(ctx, f"Unbanned {user}")

    @commands.hybrid_group()
    async def set(self, _ctx: commands.Context[CazzuBot]) -> None:
        """Mod settings."""

    @set.command(name="mute")
    async def set_mute(
        self, ctx: commands.Context[CazzuBot], *, role: discord.Role
    ) -> None:
        await db.set_mute_role(self.bot.settings, role.id)
        await window_success(ctx, f"Mute role set to {role}")

    @commands.hybrid_command()
    async def slowmode(
        self,
        ctx: commands.Context[CazzuBot],
        cooldown: int = 0,
        channel: discord.TextChannel | None = None,
    ) -> None:
        target = channel or ctx.channel
        if not isinstance(
            target,
            (
                discord.TextChannel,
                discord.VoiceChannel,
                discord.StageChannel,
                discord.Thread,
            ),
        ):
            await ctx.send("Slowmode needs a text or voice channel.")
            return
        await target.edit(slowmode_delay=cooldown)
        if cooldown == 0:
            await ctx.send("Slowmode has been turned **off**.")
        else:
            await ctx.send(
                f"Slowmode has been turned **on** with a {cooldown} "
                + "delay per message."
            )


async def on_modlog_due(bot: CazzuBot, payload: dict[str, Any]) -> None:
    """Scheduler handler for tag ``modlog`` (mute/tempban expiry)."""
    log_type = ModlogTypeEnum(payload["log_type"])
    uid = payload["uid"]
    guild = bot.guild
    if guild is None:
        return

    try:
        if log_type is ModlogTypeEnum.MUTE:
            mute_id = await db.get_mute_role(bot.settings)
            role = guild.get_role(mute_id) if mute_id else None
            if role is None:
                _log.warning(
                    "mute role %s missing; cannot lift mute for %s",
                    mute_id,
                    uid,
                )
                return
            member = await guild.fetch_member(uid)
            await member.remove_roles(role, reason="Mute expired.")

        elif log_type is ModlogTypeEnum.TEMPBAN:
            user = await bot.fetch_user(uid)
            await guild.unban(user, reason="Tempban expired.")
    except discord.NotFound:
        _log.info("user %s no longer around; nothing to revert", uid)

    _log.info(
        "%s's %s expired; reverting infraction actions...",
        uid,
        log_type.value,
    )
