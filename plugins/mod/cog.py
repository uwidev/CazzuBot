"""Mod plugin extension — moderation commands and scheduled expiries.

Single-guild port of v1's ``ext/mod.py``. Mute and temp-ban expirations are
handled by the central scheduler (tag ``modlog``); the due handler lives here
because it is pure discord side effects.
"""

import logging
from typing import Any, cast

import hikari
import lightbulb
import pendulum

from cazzubot.bot import CazzuBot
from cazzubot.models import ModlogTypeEnum
from cazzubot.window import window_error, window_info, window_success

from . import db
from .logic import ensure_future, resolve_ban_type, split_duration_reason

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

_MOD_PERMS = (
    hikari.Permissions.MODERATE_MEMBERS
    | hikari.Permissions.KICK_MEMBERS
    | hikari.Permissions.BAN_MEMBERS
)


class _ModGateDenied(Exception):
    """Marker: the command needs any mod permission the user lacks."""


@lightbulb.hook(
    lightbulb.ExecutionSteps.CHECKS, skip_when_failed=True, name="mod_gate"
)
def _mod_gate(
    _pl: lightbulb.ExecutionPipeline, ctx: lightbulb.Context
) -> None:
    """Any of moderate/kick/ban (or administrator) may use mod commands."""
    member = ctx.member
    if member is None:
        raise _ModGateDenied()
    if not (
        member.permissions
        & (_MOD_PERMS | hikari.Permissions.ADMINISTRATOR)
    ):
        raise _ModGateDenied()


@loader.error_handler
async def _on_mod_error(
    err: lightbulb.exceptions.ExecutionPipelineFailedException,
) -> bool:
    """Silently swallow denials from the mod gate (mirrors old CheckFailure)."""
    if isinstance(err.__cause__, _ModGateDenied):
        return True
    return False


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


@loader.command()
class ModCheck(
    lightbulb.SlashCommand,
    name="mod_check",
    description="Check if you have moderator permissions.",
    hooks=[_mod_gate],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond("You have moderator permissions!")


@loader.command()
class Warn(
    lightbulb.SlashCommand,
    name="warn",
    description="Warn the member, writing a modlog entry.",
    hooks=[_mod_gate],
):
    member = lightbulb.user("member", "The member to warn")
    reason = lightbulb.string("reason", "The reason")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await db.add_log(
            bot.db,
            self.member.id,
            ModlogTypeEnum.WARN,
            pendulum.now("UTC"),
            reason=self.reason,
        )
        await window_info(ctx, f"Warned {self.member}")


@loader.command()
class Mute(
    lightbulb.SlashCommand,
    name="mute",
    description="Mute the user until the given time (relative or absolute, UTC).",
    hooks=[_mod_gate],
):
    member = lightbulb.user("member", "The member to mute")
    raw = lightbulb.string(
        "raw",
        "Duration (e.g. 2h) or absolute time; blank = forever",
        default=None,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        mute_id = await db.get_mute_role(bot.settings)
        if not mute_id:
            await ctx.respond(
                "No mute role has been set (`set mute <role>`)."
            )
            return

        guild = bot.guild
        if guild is None:
            await window_error(ctx, "Run mute in the server, not DMs.")
            return
        role = bot.cache.get_role(mute_id)
        if role is None:
            await window_error(
                ctx, "Mute role no longer exists in this server."
            )
            return

        now = pendulum.now("UTC")
        duration, reason = split_duration_reason(self.raw)
        ensure_future(now, duration)

        await db.add_log(
            bot.db,
            self.member.id,
            ModlogTypeEnum.MUTE,
            now,
            expires_on=duration,
            reason=reason,
        )
        if duration:
            await bot.scheduler.add(
                "modlog",
                duration,
                {
                    "uid": self.member.id,
                    "log_type": ModlogTypeEnum.MUTE.value,
                    # the expiry must eventually fire — a mute that never
                    # lifts is a real harm; retry until it succeeds
                    "retry": True,
                },
            )
        await bot.rest.add_role_to_member(
            guild.id, self.member.id, role.id, reason=reason
        )
        await window_info(ctx, f"Muted {self.member}")


@loader.command()
class Kick(
    lightbulb.SlashCommand,
    name="kick",
    description="Kick a member, writing a modlog entry.",
    hooks=[_mod_gate],
):
    member = lightbulb.user("member", "The member to kick")
    reason = lightbulb.string("reason", "The reason", default=None)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        guild = bot.guild
        if guild is None:
            await window_error(ctx, "Run kick in the server, not DMs.")
            return
        await db.add_log(
            bot.db,
            self.member.id,
            ModlogTypeEnum.KICK,
            pendulum.now("UTC"),
            reason=self.reason,
        )
        await bot.rest.kick_member(
            guild.id,
            self.member.id,
            reason=(
                self.reason
                if self.reason is not None
                else hikari.UNDEFINED
            ),
        )
        await window_info(ctx, f"Kicked {self.member}")


@loader.command()
class Ban(
    lightbulb.SlashCommand,
    name="ban",
    description="Ban the user until the given time; without one, forever.",
    hooks=[_mod_gate],
):
    member = lightbulb.user("member", "The member to ban")
    raw = lightbulb.string(
        "raw",
        "Duration (e.g. 2h) or absolute time; blank = forever",
        default=None,
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        guild = bot.guild
        if guild is None:
            await window_error(ctx, "Run ban in the server, not DMs.")
            return

        now = pendulum.now("UTC")
        duration, reason = split_duration_reason(self.raw)
        ensure_future(now, duration)

        ban_type = resolve_ban_type(duration)
        await db.add_log(
            bot.db,
            self.member.id,
            ban_type,
            now,
            expires_on=duration,
            reason=reason,
        )
        if duration:
            await bot.scheduler.add(
                "modlog",
                duration,
                {
                    "uid": self.member.id,
                    "log_type": ban_type.value,
                    # the expiry must eventually fire — see the mute path
                    "retry": True,
                },
            )
        await bot.rest.ban_member(
            guild.id,
            self.member.id,
            reason=reason if reason is not None else hikari.UNDEFINED,
        )
        await window_info(ctx, f"Banned {self.member}")


async def _drop_expiry_tasks(
    bot: CazzuBot, uid: int, log_type: str
) -> None:
    """Drop pending ``modlog`` expiry tasks matching a user + log type."""
    for task in await bot.scheduler.get("modlog"):
        payload = task.payload
        if (
            payload.get("uid") == uid
            and payload.get("log_type") == log_type
        ):
            await bot.scheduler.drop(task.id)


@loader.command()
class Unmute(
    lightbulb.SlashCommand,
    name="unmute",
    description="Remove the mute role and any pending mute expiry.",
    hooks=[_mod_gate],
):
    member = lightbulb.user("member", "The member to unmute")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        guild = bot.guild
        mute_id = await db.get_mute_role(bot.settings)
        if guild is None:
            await window_error(ctx, "Run unmute in the server, not DMs.")
            return
        role = bot.cache.get_role(mute_id) if mute_id else None
        member = bot.cache.get_member(guild.id, self.member.id)
        if (
            role is not None
            and member is not None
            and role.id in member.role_ids
        ):
            await bot.rest.remove_role_from_member(
                guild.id, self.member.id, role.id, reason="Unmuted."
            )
        await _drop_expiry_tasks(bot, self.member.id, "mute")
        await window_info(ctx, f"Unmuted {self.member}")


@loader.command()
class Unban(
    lightbulb.SlashCommand,
    name="unban",
    description="Unban a user and drop any pending tempban expiry.",
    hooks=[_mod_gate],
):
    user = lightbulb.user("user", "The user to unban")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        guild = bot.guild
        if guild is None:
            await window_error(ctx, "Run unban in the server, not DMs.")
            return
        await bot.rest.unban_member(
            guild.id, self.user.id, reason="Unbanned."
        )
        await _drop_expiry_tasks(bot, self.user.id, "tempban")
        await window_info(ctx, f"Unbanned {self.user}")


mod_set = lightbulb.Group("set", "Mod settings.")


@mod_set.register
class SetMute(
    lightbulb.SlashCommand,
    name="mute",
    description="Set the mute role.",
    hooks=[_mod_gate],
):
    role = lightbulb.role("role", "The mute role")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await db.set_mute_role(bot.settings, self.role.id)
        await window_success(ctx, f"Mute role set to {self.role}")


loader.command(mod_set)


@loader.command()
class Slowmode(
    lightbulb.SlashCommand,
    name="slowmode",
    description="Set a channel's slowmode delay.",
    hooks=[_mod_gate],
):
    cooldown = lightbulb.integer(
        "cooldown", "Seconds between messages (0 = off)", default=0
    )
    channel = lightbulb.channel(
        "channel",
        "The channel (default: this channel)",
        default=None,
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        target_id = (
            self.channel.id if self.channel is not None else ctx.channel_id
        )
        await bot.rest.edit_channel(
            target_id, rate_limit_per_user=self.cooldown
        )
        if self.cooldown == 0:
            await ctx.respond("Slowmode has been turned **off**.")
        else:
            await ctx.respond(
                f"Slowmode has been turned **on** with a {self.cooldown} "
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
            role = bot.cache.get_role(mute_id) if mute_id else None
            if role is None:
                _log.warning(
                    "mute role %s missing; cannot lift mute for %s",
                    mute_id,
                    uid,
                )
                return
            member = await bot.rest.fetch_member(guild.id, uid)
            await bot.rest.remove_role_from_member(
                guild.id, member.id, role.id, reason="Mute expired."
            )

        elif log_type is ModlogTypeEnum.TEMPBAN:
            user = await bot.rest.fetch_user(uid)
            await bot.rest.unban_member(
                guild.id, user.id, reason="Tempban expired."
            )
    except hikari.NotFoundError:
        _log.info("user %s no longer around; nothing to revert", uid)

    _log.info(
        "%s's %s expired; reverting infraction actions...",
        uid,
        log_type.value,
    )
