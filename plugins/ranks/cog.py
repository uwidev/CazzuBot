"""Ranks plugin cog — per-window rank threshold management."""

import json

import discord
from discord.ext import commands

from cazzubot import templates, utils
from cazzubot.models import WindowEnum

from . import db as ranks_db
from .logic import formatter


def _parse_mode(raw: str) -> WindowEnum | None:
	try:
		return WindowEnum(raw.strip().lower())
	except ValueError:
		return None


class RanksCog(commands.Cog):
	"""Ranked roles based on level thresholds."""

	def __init__(self, bot) -> None:
		self.bot = bot

	async def cog_check(self, ctx: commands.Context) -> bool:
		perms = ctx.channel.permissions_for(ctx.author)
		return bool(perms.administrator)

	@commands.group(
		name="rank", aliases=["ranks"], invoke_without_command=True
	)
	async def rank(self, ctx: commands.Context) -> None:
		pass

	@rank.command(name="add")
	async def rank_add(
		self,
		ctx: commands.Context,
		level: int,
		role: discord.Role,
		mode: WindowEnum = WindowEnum.SEASONAL,
	) -> None:
		"""Add a rank role at a level threshold."""
		if not 1 <= level <= 999:
			await ctx.send("Level must be between 1-999.")
			return
		await ranks_db.add(self.bot.db, role.id, level, mode=mode)
		await ctx.message.add_reaction("👍")

	@rank.command(name="remove", aliases=["del"])
	async def rank_remove(
		self,
		ctx: commands.Context,
		arg: discord.Role | int,
		mode: WindowEnum = WindowEnum.SEASONAL,
	) -> None:
		"""Remove a rank by role or threshold level."""
		await ranks_db.delete(
			self.bot.db, arg if isinstance(arg, int) else arg.id, mode
		)
		await ctx.message.add_reaction("👍")

	@rank.command(name="clean")
	async def rank_clean(self, ctx: commands.Context) -> None:
		"""Remove ranks whose roles no longer exist in the guild."""
		rows = await ranks_db.get(self.bot.db)
		removed = [
			r["rid"] for r in rows if not ctx.guild.get_role(r["rid"])
		]
		await ranks_db.batch_delete(self.bot.db, removed)
		await ctx.message.add_reaction("👍")

	@rank.command(name="clear", aliases=["purge", "drop"])
	async def rank_clear(
		self,
		ctx: commands.Context,
		mode: WindowEnum = WindowEnum.SEASONAL,
	) -> None:
		await ranks_db.drop(self.bot.db, mode)
		await ctx.message.add_reaction("👍")

	@rank.group(name="set")
	async def rank_set(self, ctx: commands.Context) -> None:
		pass

	@rank_set.command(name="enabled")
	async def rank_set_enabled(
		self,
		ctx: commands.Context,
		val: bool,
		mode: WindowEnum = WindowEnum.SEASONAL,
	) -> None:
		await ranks_db.set_enabled(self.bot.settings, val, mode)
		await ctx.message.add_reaction("👍")

	@rank_set.command(name="keepOld")
	async def rank_set_keep_old(
		self,
		ctx: commands.Context,
		val: bool,
		mode: WindowEnum = WindowEnum.SEASONAL,
	) -> None:
		await ranks_db.set_keep_old(self.bot.settings, val, mode)
		await ctx.message.add_reaction("👍")

	@rank_set.command(name="message", aliases=["msg"])
	async def rank_set_message(
		self,
		ctx: commands.Context,
		*,
		message: str,
		mode: WindowEnum = WindowEnum.SEASONAL,
	) -> None:
		"""Set the rank-up message JSON.

		Append a window name ("lifetime"/"seasonal") after the closing brace to
		configure a specific window; otherwise the default argument applies.
		"""
		last_closing = len(message) - 1 - message[::-1].find("}")
		tail = message[last_closing + 1 :].strip()
		message = message[: last_closing + 1]
		if tail:
			parsed = _parse_mode(tail)
			if parsed is None:
				raise commands.BadArgument(
					f"Unable to convert mode {tail} to type WindowEnum"
				)
			mode = parsed

		decoded = await templates.verify(
			ctx, message, formatter, member=ctx.author
		)
		await ranks_db.set_message(self.bot.settings, decoded, mode)
		await ctx.message.add_reaction("👍")

	@rank.command(name="demo")
	async def rank_demo(
		self,
		ctx: commands.Context,
		mode: WindowEnum = WindowEnum.SEASONAL,
	) -> None:
		msg_json = await ranks_db.get_message(self.bot.settings, mode)
		if not msg_json:
			await ctx.send("No rank-up message has been set.")
			return
		utils.deep_map(msg_json, formatter, member=ctx.author)
		content, embed, embeds = templates.prepare(msg_json)
		await ctx.send(content, embed=embed, embeds=embeds)

	@rank.command(name="raw")
	async def rank_raw(
		self,
		ctx: commands.Context,
		mode: WindowEnum = WindowEnum.SEASONAL,
	) -> None:
		msg_json = await ranks_db.get_message(self.bot.settings, mode)
		await ctx.send(f"```{json.dumps(msg_json, indent=2)}```")
