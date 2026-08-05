"""Mod plugin — warn/mute/kick/ban with modlogs and scheduled expiry.

Single-guild port of v1's ``ext/mod.py`` + ``src/db/modlog.py``. Mute and
temp-ban expirations are handled by the central scheduler (tag ``modlog``).
"""

import logging

import discord
import pendulum
from discord.ext import commands

from cazzubot import Plugin
from cazzubot.window import window_info, window_success
from cazzubot.models import ModlogStatusEnum, ModlogTypeEnum
from cazzubot.timeparse import (
	InvalidTimeError,
	is_future,
	normalize_time_str,
)

_log = logging.getLogger(__name__)

SCHEMA = [
	"""
	CREATE TABLE IF NOT EXISTS modlog (
		id         INTEGER PRIMARY KEY AUTOINCREMENT,
		uid        INTEGER NOT NULL,
		log_type   TEXT NOT NULL,
		given_on   TEXT NOT NULL,
		status     TEXT NOT NULL DEFAULT 'active',
		expires_on TEXT,
		reason     TEXT
	)
	""",
]

MUTE_ROLE_KEY = "mod.mute_role"


# -- db ---------------------------------------------------------------------


async def add_log(
	db,
	uid: int,
	log_type: ModlogTypeEnum,
	given_on: pendulum.DateTime,
	*,
	expires_on: pendulum.DateTime | None = None,
	reason: str | None = None,
) -> None:
	await db.execute(
		"""
		INSERT INTO modlog (uid, log_type, given_on, status, expires_on, reason)
		VALUES (?, ?, ?, ?, ?, ?)
		""",
		uid,
		log_type.value,
		given_on.isoformat(),
		ModlogStatusEnum.ACTIVE.value,
		expires_on.isoformat() if expires_on else None,
		reason,
	)


async def get_mute_role(settings) -> int | None:
	return await settings.get(MUTE_ROLE_KEY)


async def set_mute_role(settings, rid: int) -> None:
	await settings.set(MUTE_ROLE_KEY, rid)


async def on_modlog_due(bot, payload: dict) -> None:
	"""Scheduler handler for tag ``modlog`` (mute/tempban expiry)."""
	log_type = ModlogTypeEnum(payload["log_type"])
	uid = payload["uid"]
	guild = bot.guild
	if guild is None:
		return

	try:
		if log_type is ModlogTypeEnum.MUTE:
			mute_id = await get_mute_role(bot.settings)
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


def split_duration_reason(raw: str | None) -> tuple[object, str]:
	"""Parse an optional leading duration from the rest of the string."""
	if not raw:
		return None, ""
	if " " in raw:
		dur_raw, rest = raw.split(" ", 1)
	else:
		dur_raw, rest = raw, ""
	try:
		return normalize_time_str(dur_raw), rest
	except InvalidTimeError:
		return None, raw


class ModCog(commands.Cog):
	"""Moderation actions with a persistent modlog."""

	def __init__(self, bot) -> None:
		self.bot = bot

	async def cog_check(self, ctx: commands.Context) -> bool:
		perms = ctx.channel.permissions_for(ctx.author)
		return any(
			[
				perms.moderate_members,
				perms.kick_members,
				perms.ban_members,
			]
		)

	@commands.hybrid_command()
	async def mod_check(self, ctx: commands.Context) -> None:
		"""Check if you have moderator permissions."""
		await ctx.send("You have moderator permissions!")

	@commands.hybrid_command()
	async def warn(
		self, ctx: commands.Context, member: discord.Member, *, reason: str
	) -> None:
		"""Warn the member, writing a modlog entry."""
		await add_log(
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
		ctx: commands.Context,
		member: discord.Member,
		*,
		raw: str = None,
	) -> None:
		"""Mute the user until the given time (relative or absolute, UTC)."""
		mute_id = await get_mute_role(self.bot.settings)
		if not mute_id:
			await ctx.send(
				"No mute role has been set (`set mute <role>`)."
			)
			return

		now = pendulum.now("UTC")
		duration, reason = split_duration_reason(raw)
		if duration and not is_future(now, duration):
			raise commands.BadArgument(
				f"{duration} is not a time in the future!"
			)

		await add_log(
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

		role = ctx.guild.get_role(mute_id)
		if role is None:
			await ctx.send("Mute role no longer exists in this server.")
			return
		await member.add_roles(role, reason=reason)
		await window_info(ctx, f"Muted {member}")

	@commands.hybrid_command()
	async def kick(
		self,
		ctx: commands.Context,
		member: discord.Member,
		*,
		reason: str = None,
	) -> None:
		"""Kick a member, writing a modlog entry."""
		await add_log(
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
		ctx: commands.Context,
		member: discord.Member,
		*,
		raw: str = None,
	) -> None:
		"""Ban the user until the given time; without one, forever."""
		now = pendulum.now("UTC")
		duration, reason = split_duration_reason(raw)
		if duration and not is_future(now, duration):
			raise commands.BadArgument(
				f"{duration} is not a time in the future!"
			)

		ban_type = (
			ModlogTypeEnum.TEMPBAN if duration else ModlogTypeEnum.BAN
		)
		await add_log(
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
		self, ctx: commands.Context, member: discord.Member
	) -> None:
		"""Remove the mute role and any pending mute expiry."""
		mute_id = await get_mute_role(self.bot.settings)
		role = ctx.guild.get_role(mute_id) if mute_id else None
		if role and role in member.roles:
			await member.remove_roles(role, reason="Unmuted.")
		for task in await self.bot.scheduler.get("modlog"):
			payload = task["payload"]
			if (
				payload.get("uid") == member.id
				and payload.get("log_type") == "mute"
			):
				await self.bot.scheduler.drop(task["id"])
		await window_info(ctx, f"Unmuted {member}")

	@commands.hybrid_command()
	async def unban(
		self, ctx: commands.Context, user: discord.User
	) -> None:
		"""Unban a user and drop any pending tempban expiry."""
		await ctx.guild.unban(user, reason="Unbanned.")
		for task in await self.bot.scheduler.get("modlog"):
			payload = task["payload"]
			if (
				payload.get("uid") == user.id
				and payload.get("log_type") == "tempban"
			):
				await self.bot.scheduler.drop(task["id"])
		await window_info(ctx, f"Unbanned {user}")

	@commands.hybrid_group()
	async def set(self, ctx: commands.Context) -> None:
		"""Mod settings."""

	@set.command(name="mute")
	async def set_mute(
		self, ctx: commands.Context, *, role: discord.Role
	) -> None:
		await set_mute_role(self.bot.settings, role.id)
		await window_success(ctx, f"Mute role set to {role}")

	@commands.hybrid_command()
	async def slowmode(
		self,
		ctx: commands.Context,
		cooldown: int = 0,
		channel: discord.TextChannel = None,
	) -> None:
		channel = channel or ctx.channel
		await channel.edit(slowmode_delay=cooldown)
		if cooldown == 0:
			await ctx.send("Slowmode has been turned **off**.")
		else:
			await ctx.send(
				f"Slowmode has been turned **on** with a {cooldown} "
				"delay per message."
			)


class ModPlugin(Plugin):
	name = "mod"
	schema = SCHEMA
	cogs = [ModCog]
	scheduled = {"modlog": on_modlog_due}


plugin = ModPlugin()
