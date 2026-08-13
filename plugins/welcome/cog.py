"""Welcome plugin extension — welcomes new members who finish onboarding.

Two modes:

- ``pending``: welcome when the member's onboarding ``pending`` flag clears
- ``role``: welcome when the member gains the monitored role

A ``last_welcomed_id`` guard prevents double welcomes (v1's hard-won fix).
"""

import asyncio
import json
import logging
from typing import Any, cast

import hikari
import lightbulb

from cazzubot import templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.models import MemberSnapshot, WelcomeModeEnum
from cazzubot.window import window_success
from lightbulb.prefab import checks as prefab_checks

from .logic import should_welcome

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

_ADMIN = prefab_checks.has_permissions(hikari.Permissions.ADMINISTRATOR)

welcome = lightbulb.Group("welcome", "Welcome message settings.")
welcome_set = welcome.subgroup("set", "Set welcome settings.")

last_welcomed_id: int | None = None


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


def formatter(s: str, *, member: MemberSnapshot) -> str:
    """Placeholders: {avatar} {name} {mention} {id}"""
    return utils.format_member(s, member)


@loader.listener(hikari.MemberUpdateEvent)
async def on_member_update(event: hikari.MemberUpdateEvent) -> None:
    """Welcome said user when they finish verification."""
    global last_welcomed_id
    bot = cast(CazzuBot, event.app)
    if not utils.in_guild(bot, event.guild_id):
        return
    enabled = await bot.settings.get("welcome.enabled", False)
    if not enabled:
        return

    cid = await bot.settings.get("welcome.cid")
    channel = utils.text_channel(bot, cid)
    if channel is None:
        _log.warning("welcome channel %s not found", cid)
        return

    message = await bot.settings.get("welcome.message")
    default_rid = await bot.settings.get("welcome.default_rid")
    monitor_rid = await bot.settings.get("welcome.monitor_rid")
    mode_raw = await bot.settings.get(
        "welcome.mode", WelcomeModeEnum.PENDING.value
    )
    try:
        mode = WelcomeModeEnum(mode_raw)
    except ValueError:
        _log.warning("invalid welcome.mode setting: %r", mode_raw)
        return

    role = bot.cache.get_role(default_rid) if default_rid else None
    member = event.member
    before = event.old_member or member

    if should_welcome(
        mode,
        before_pending=before.is_pending is True,
        after_pending=member.is_pending is True,
        before_role_ids=set(map(int, before.role_ids)),
        after_role_ids=set(map(int, member.role_ids)),
        monitor_rid=monitor_rid,
        member_id=member.id,
        last_welcomed_id=last_welcomed_id,
    ):
        if mode is WelcomeModeEnum.PENDING:
            last_welcomed_id = member.id  # race guard
        await _send_welcome(channel, member, message)
        if mode is WelcomeModeEnum.PENDING and role:
            await bot.rest.add_role_to_member(
                event.guild_id, member.id, role.id
            )


async def _send_welcome(
    channel: Any,
    member: hikari.Member,
    msg_json: dict[str, Any] | None,
) -> None:
    await asyncio.sleep(1)  # let user UI update so the ping works
    if not msg_json:
        return
    utils.deep_map(
        msg_json, formatter, member=utils.member_snapshot(member)
    )
    await templates.send(channel, msg_json)


# -- configuration ----------------------------------------------------------


@welcome_set.register
class SetEnabled(
    lightbulb.SlashCommand,
    name="enabled",
    description="Enable or disable welcome messages.",
    hooks=[_ADMIN],
):
    enabled = lightbulb.boolean(
        "enabled", "Whether welcome messages are on"
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await bot.settings.set("welcome.enabled", self.enabled)
        await window_success(
            ctx,
            "Welcome messages enabled"
            if self.enabled
            else "Welcome messages disabled",
        )


@welcome_set.register
class SetRole(
    lightbulb.SlashCommand,
    name="role",
    description="Set the default role given after welcome.",
    hooks=[_ADMIN],
):
    role = lightbulb.role("role", "The default role")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await bot.settings.set("welcome.default_rid", self.role.id)
        await window_success(ctx, f"Default role set to {self.role}")


@welcome_set.register
class SetChannel(
    lightbulb.SlashCommand,
    name="channel",
    description="Set the welcome channel.",
    hooks=[_ADMIN],
):
    channel = lightbulb.channel(
        "channel",
        "The welcome channel",
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await bot.settings.set("welcome.cid", self.channel.id)
        await window_success(ctx, f"Welcome channel set to {self.channel}")


@welcome_set.register
class SetMessage(
    lightbulb.SlashCommand,
    name="message",
    description="Set the welcome message JSON (embed-capable).",
    hooks=[_ADMIN],
):
    message = lightbulb.string("message", "The welcome message JSON")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Set the welcome message JSON (embed-capable).

        Use https://message.style/ or discohook.org to build one; placeholders
        {avatar} {name} {mention} {id} are supported.
        """
        bot = _bot(ctx)
        decoded = templates.verify(
            self.message,
            formatter,
            member=utils.member_snapshot(ctx.member or ctx.user),
        )
        await bot.settings.set("welcome.message", decoded)
        await window_success(ctx, "Welcome message set")


@welcome_set.register
class SetMode(
    lightbulb.SlashCommand,
    name="mode",
    description="Set the welcome trigger mode.",
    hooks=[_ADMIN],
):
    mode = lightbulb.string(
        "mode",
        "pending = onboarding flag clears; role = gains the monitored role",
        choices=[
            lightbulb.Choice("Pending", "pending"),
            lightbulb.Choice("Role", "role"),
        ],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        try:
            mode_enum = WelcomeModeEnum(self.mode.lower())
        except ValueError:
            raise UserInputError(
                f"Mode must be one of {[m.value for m in WelcomeModeEnum]}"
            ) from None
        await bot.settings.set("welcome.mode", mode_enum.value)
        await window_success(ctx, f"Welcome mode set to {mode_enum.value}")


@welcome_set.register
class SetMonitor(
    lightbulb.SlashCommand,
    name="monitor",
    description="Set the role whose gain triggers the welcome.",
    hooks=[_ADMIN],
):
    role = lightbulb.role("role", "The monitored role")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        await bot.settings.set("welcome.monitor_rid", self.role.id)
        await window_success(ctx, f"Monitored role set to {self.role}")


@welcome.register
class Demo(
    lightbulb.SlashCommand,
    name="demo",
    description="Preview the welcome message with you as the new user.",
    hooks=[_ADMIN],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        msg_json = await bot.settings.get("welcome.message")
        if not msg_json:
            await ctx.respond("No welcome message has been set.")
            return
        utils.deep_map(
            msg_json,
            formatter,
            member=utils.member_snapshot(ctx.member or ctx.user),
        )
        await templates.send(ctx, msg_json)


@welcome.register
class Raw(
    lightbulb.SlashCommand,
    name="raw",
    description="Dump the raw stored welcome message JSON.",
    hooks=[_ADMIN],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        msg_json = await bot.settings.get("welcome.message")
        await ctx.respond(f"```{json.dumps(msg_json, indent=2)}```")


loader.command(welcome)
