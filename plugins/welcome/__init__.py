"""Welcome plugin — welcomes new members who finish onboarding.

Single-guild port of v1's ``ext/welcome.py`` + ``src/db/welcome.py``. All
settings live in the settings store under ``welcome.`` keys. Two modes:

- ``pending``: welcome when the member's onboarding ``pending`` flag clears
- ``role``: welcome when the member gains the monitored role

A ``last_welcomed_id`` guard prevents double welcomes (v1's hard-won fix).
"""

import asyncio
import json
import logging
from typing import Any

import discord
from discord.ext import commands

from cazzubot import Plugin, templates, utils
from cazzubot.bot import CazzuBot
from cazzubot.window import window_success
from cazzubot.models import WelcomeModeEnum

from .logic import should_welcome

_log = logging.getLogger(__name__)

KEYS = ("enabled", "cid", "default_rid", "monitor_rid", "mode", "message")


def formatter(s: str, *, member: discord.Member) -> str:
    """Placeholders: {avatar} {name} {mention} {id}"""
    return s.format(
        avatar=member.display_avatar.url,
        name=member.display_name,
        mention=member.mention,
        id=member.id,
    )


class WelcomeCog(commands.Cog):
    """Welcomes new members and configures the welcome message."""

    def __init__(self, bot: CazzuBot) -> None:
        self.bot = bot
        self.last_welcomed_id: int | None = None

    @commands.Cog.listener()
    async def on_member_update(
        self, before: discord.Member, after: discord.Member
    ) -> None:
        """Welcome said user when they finish verification."""
        enabled = await self.bot.settings.get("welcome.enabled", False)
        if not enabled:
            return

        cid = await self.bot.settings.get("welcome.cid")
        channel = before.guild.get_channel(cid) if cid else None
        if not isinstance(channel, discord.abc.Messageable):
            _log.warning("welcome channel %s not found", cid)
            return

        message = await self.bot.settings.get("welcome.message")
        default_rid = await self.bot.settings.get("welcome.default_rid")
        monitor_rid = await self.bot.settings.get("welcome.monitor_rid")
        mode_raw = await self.bot.settings.get(
            "welcome.mode", WelcomeModeEnum.PENDING.value
        )
        try:
            mode = WelcomeModeEnum(mode_raw)
        except ValueError:
            _log.warning("invalid welcome.mode setting: %r", mode_raw)
            return

        role = before.guild.get_role(default_rid) if default_rid else None

        if should_welcome(
            mode,
            before_pending=before.pending,
            after_pending=after.pending,
            before_role_ids={r.id for r in before.roles},
            after_role_ids={r.id for r in after.roles},
            monitor_rid=monitor_rid,
            member_id=after.id,
            last_welcomed_id=self.last_welcomed_id,
        ):
            if mode is WelcomeModeEnum.PENDING:
                self.last_welcomed_id = after.id  # race guard
            await self._send_welcome(channel, after, message)
            if mode is WelcomeModeEnum.PENDING and role:
                await after.add_roles(role)

    async def _send_welcome(
        self,
        sendable: discord.abc.Messageable,
        member: discord.Member,
        msg_json: dict[str, Any] | None,
    ) -> None:
        await asyncio.sleep(1)  # let user UI update so the ping works
        if not msg_json:
            return
        utils.deep_map(msg_json, formatter, member=member)
        await templates.send(sendable, msg_json)

    # -- configuration ------------------------------------------------------

    @commands.hybrid_group()
    @commands.has_permissions(administrator=True)
    async def welcome(self, _ctx: commands.Context[CazzuBot]) -> None:
        """Entry command for welcome settings."""

    @welcome.group(name="set")
    async def welcome_set(self, _ctx: commands.Context[CazzuBot]) -> None:
        """Set command entry."""

    @welcome_set.command(name="enabled")
    async def welcome_set_enabled(
        self, ctx: commands.Context[CazzuBot], enabled: bool
    ) -> None:
        await self.bot.settings.set("welcome.enabled", enabled)
        await window_success(
            ctx,
            "Welcome messages enabled"
            if enabled
            else "Welcome messages disabled",
        )

    @welcome_set.command(name="verify")
    async def welcome_set_verify_first(
        self, ctx: commands.Context[CazzuBot], verify_first: bool
    ) -> None:
        await self.bot.settings.set("welcome.verify_first", verify_first)
        await window_success(
            ctx,
            "Verify-first enabled"
            if verify_first
            else "Verify-first disabled",
        )

    @welcome_set.command(name="role")
    async def welcome_set_rid(
        self, ctx: commands.Context[CazzuBot], role: discord.Role
    ) -> None:
        await self.bot.settings.set("welcome.default_rid", role.id)
        await window_success(ctx, f"Default role set to {role}")

    @welcome_set.command(name="channel")
    async def welcome_set_cid(
        self, ctx: commands.Context[CazzuBot], channel: discord.TextChannel
    ) -> None:
        await self.bot.settings.set("welcome.cid", channel.id)
        await window_success(ctx, f"Welcome channel set to {channel}")

    @welcome_set.command(name="message", aliases=["msg"])
    async def welcome_set_message(
        self, ctx: commands.Context[CazzuBot], *, message: str
    ) -> None:
        """Set the welcome message JSON (embed-capable).

        Use https://message.style/ or discohook.org to build one; placeholders
        {avatar} {name} {mention} {id} are supported.
        """
        decoded = templates.verify(message, formatter, member=ctx.author)
        await self.bot.settings.set("welcome.message", decoded)
        await window_success(ctx, "Welcome message set")

    @welcome_set.command(name="mode")
    async def welcome_set_mode(
        self, ctx: commands.Context[CazzuBot], *, mode: str
    ) -> None:
        try:
            mode_enum = WelcomeModeEnum(mode.lower())
        except ValueError:
            raise commands.BadArgument(
                f"Mode must be one of {[m.value for m in WelcomeModeEnum]}"
            ) from None
        await self.bot.settings.set("welcome.mode", mode_enum.value)
        await window_success(ctx, f"Welcome mode set to {mode_enum.value}")

    @welcome_set.command(name="monitor")
    async def welcome_set_monitor(
        self, ctx: commands.Context[CazzuBot], *, role: discord.Role
    ) -> None:
        await self.bot.settings.set("welcome.monitor_rid", role.id)
        await window_success(ctx, f"Monitored role set to {role}")

    @welcome.command(name="demo")
    async def welcome_demo(self, ctx: commands.Context[CazzuBot]) -> None:
        """Preview the welcome message with you as the new user."""
        msg_json = await self.bot.settings.get("welcome.message")
        if not msg_json:
            await ctx.send("No welcome message has been set.")
            return
        utils.deep_map(msg_json, formatter, member=ctx.author)
        await templates.send(ctx, msg_json)

    @welcome.command(name="raw")
    async def welcome_raw(self, ctx: commands.Context[CazzuBot]) -> None:
        """Dump the raw stored welcome message JSON."""
        msg_json = await self.bot.settings.get("welcome.message")
        await ctx.send(f"```{json.dumps(msg_json, indent=2)}```")


class WelcomePlugin(Plugin):
    name = "welcome"
    cogs = [WelcomeCog]


plugin = WelcomePlugin()
