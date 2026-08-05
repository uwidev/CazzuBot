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

import discord
from discord.ext import commands

from cazzubot import Plugin, templates, utils
from cazzubot.models import WelcomeModeEnum

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

	def __init__(self, bot) -> None:
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
		if channel is None:
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

		if mode is WelcomeModeEnum.PENDING:
			if (
				before.pending != after.pending
				and after.id != self.last_welcomed_id
			):
				self.last_welcomed_id = after.id  # race guard
				await self._send_welcome(channel, after, message)
				if role:
					await after.add_roles(role)
		elif mode is WelcomeModeEnum.ROLE:
			roles_diff = set(after.roles) - set(before.roles)
			if roles_diff and monitor_rid == roles_diff.pop().id:
				await self._send_welcome(channel, after, message)

	async def _send_welcome(
		self,
		sendable: discord.PartialMessageable,
		member: discord.Member,
		msg_json: dict | None,
	) -> None:
		await asyncio.sleep(1)  # let user UI update so the ping works
		if not msg_json:
			return
		utils.deep_map(msg_json, formatter, member=member)
		content, embed, embeds = templates.prepare(msg_json)
		await sendable.send(content, embed=embed, embeds=embeds)

	# -- configuration ------------------------------------------------------

	@commands.group()
	@commands.has_permissions(administrator=True)
	async def welcome(self, ctx: commands.Context) -> None:
		"""Entry command for welcome settings."""

	@welcome.group(name="set")
	async def welcome_set(self, ctx: commands.Context) -> None:
		"""Set command entry."""

	@welcome_set.command(name="enabled")
	async def welcome_set_enabled(
		self, ctx: commands.Context, enabled: bool
	) -> None:
		await self.bot.settings.set("welcome.enabled", enabled)
		await ctx.message.add_reaction("👍")

	@welcome_set.command(name="verify")
	async def welcome_set_verify_first(
		self, ctx: commands.Context, verify_first: bool
	) -> None:
		await self.bot.settings.set("welcome.verify_first", verify_first)
		await ctx.message.add_reaction("👍")

	@welcome_set.command(name="role")
	async def welcome_set_rid(
		self, ctx: commands.Context, role: discord.Role
	) -> None:
		await self.bot.settings.set("welcome.default_rid", role.id)
		await ctx.message.add_reaction("👍")

	@welcome_set.command(name="channel")
	async def welcome_set_cid(
		self, ctx: commands.Context, channel: discord.TextChannel
	) -> None:
		await self.bot.settings.set("welcome.cid", channel.id)
		await ctx.message.add_reaction("👍")

	@welcome_set.command(name="message", aliases=["msg"])
	async def welcome_set_message(
		self, ctx: commands.Context, *, message: str
	) -> None:
		"""Set the welcome message JSON (embed-capable).

		Use https://message.style/ or discohook.org to build one; placeholders
		{avatar} {name} {mention} {id} are supported.
		"""
		decoded = await templates.verify(
			ctx, message, formatter, member=ctx.author
		)
		await self.bot.settings.set("welcome.message", decoded)
		await ctx.message.add_reaction("👍")

	@welcome_set.command(name="mode")
	async def welcome_set_mode(
		self, ctx: commands.Context, *, mode: str
	) -> None:
		try:
			mode_enum = WelcomeModeEnum(mode.lower())
		except ValueError:
			raise commands.BadArgument(
				f"Mode must be one of {[m.value for m in WelcomeModeEnum]}"
			) from None
		await self.bot.settings.set("welcome.mode", mode_enum.value)
		await ctx.message.add_reaction("👍")

	@welcome_set.command(name="monitor")
	async def welcome_set_monitor(
		self, ctx: commands.Context, *, role: discord.Role
	) -> None:
		await self.bot.settings.set("welcome.monitor_rid", role.id)
		await ctx.message.add_reaction("👍")

	@welcome.command(name="demo")
	async def welcome_demo(self, ctx: commands.Context) -> None:
		"""Preview the welcome message with you as the new user."""
		msg_json = await self.bot.settings.get("welcome.message")
		if not msg_json:
			await ctx.send("No welcome message has been set.")
			return
		utils.deep_map(msg_json, formatter, member=ctx.author)
		content, embed, embeds = templates.prepare(msg_json)
		await ctx.send(content, embed=embed, embeds=embeds)

	@welcome.command(name="raw")
	async def welcome_raw(self, ctx: commands.Context) -> None:
		"""Dump the raw stored welcome message JSON."""
		msg_json = await self.bot.settings.get("welcome.message")
		await ctx.send(f"```{json.dumps(msg_json, indent=2)}```")


class WelcomePlugin(Plugin):
	name = "welcome"
	cogs = [WelcomeCog]


plugin = WelcomePlugin()
