"""Per-guild ranked roles based on levels.

Remember that levels also based on experience.
"""

import json
import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src import db, rank, user_json, utility
from src.db.table import WindowEnum

if TYPE_CHECKING:
	from main import CazzuBot


_log = logging.getLogger(__name__)


class Ranks(commands.Cog):
	def __init__(self, bot):
		self.bot: CazzuBot = bot

	async def cog_check(self, ctx: commands.Context) -> bool:
		perms = ctx.channel.permissions_for(ctx.author)
		return any([perms.administrator])

	@commands.group(alias="ranks")
	async def rank(self, ctx: commands.Context):
		pass

	@rank.command(name="add")
	async def rank_add(
		self,
		ctx: commands.Context,
		level: int,
		role: discord.Role,
		mode: WindowEnum = WindowEnum.SEASONAL,
	):
		"""Add the rank into the guild's settings at said threshold."""
		if level <= 0 or level > 999:
			msg = "Level must be between 1-999."
			await ctx.send(msg)
			return

		gid = ctx.guild.id
		rid = role.id
		await db.rank_threshold.add(
			self.bot.pool,
			db.table.RankThreshold(gid, rid, level, mode=mode),
		)

		await ctx.message.add_reaction("👍")

	@rank.command(name="remove", aliases=["del"])
	async def rank_remove(
		self,
		ctx: commands.Context,
		arg: discord.Role | int,
		mode: WindowEnum = WindowEnum.SEASONAL,
	):
		"""Remove the rank from the guild by role or level."""
		gid = ctx.guild.id
		payload = arg if isinstance(arg, int) else arg.id
		await db.rank_threshold.delete(self.bot.pool, gid, payload)

	@rank.command(name="clean")
	async def rank_clean(self, ctx: commands.Context):
		"""Remove ranks which can no longer be referenced because they were deleted."""
		gid = ctx.guild.id
		rids = []
		payload = await db.rank_threshold.get_all_windows(
			self.bot.pool, gid
		)

		rids += [p.get("rid") for p in payload]
		roles = [ctx.guild.get_role(rid) for rid in rids]
		removed_rids = [rids[i] for i in range(len(roles)) if not roles[i]]
		await db.rank_threshold.batch_delete(
			self.bot.pool, gid, removed_rids
		)

	@rank.command(
		name="clear",
		aliases=["purge", "drop"],
	)
	async def rank_clear(
		self,
		ctx: commands.Context,
		mode: WindowEnum = WindowEnum.SEASONAL,
	):
		gid = ctx.guild.id
		await db.rank_threshold.drop(self.bot.pool, gid, mode)

	@rank.group(name="set")
	async def rank_set(self, ctx):
		pass

	@rank_set.command(name="enabled")
	async def rank_set_enabled(
		self,
		ctx: commands.Context,
		val: bool,
		mode: WindowEnum = WindowEnum.SEASONAL,
	):
		gid = ctx.guild.id
		await db.rank.set_enabled(self.bot.pool, gid, val, mode=mode)

	@rank_set.command(name="keepOld")
	async def rank_set_keep_old(
		self,
		ctx: commands.Context,
		val: bool,
		mode: WindowEnum = WindowEnum.SEASONAL,
	):
		gid = ctx.guild.id
		await db.rank.set_keep_old(self.bot.pool, gid, val, mode=mode)

	@rank_set.command(name="message", aliases=["msg"])
	async def rank_set_message(
		self,
		ctx: commands.Context,
		*,
		message: str,
		mode: WindowEnum = WindowEnum.SEASONAL,
	):
		"""Set the message sent when a user ranks up.

		By default, sets the message for seasonanl ranks. However, you can specificy the
		rank type at the end of the command due to manual parsing.

		The way discord parses commands, the first keyword argument will consume the
		entire message, meaning None will be passed to mode, which it will then use the
		default argument.
		"""
		last_closing_bracker_index = (
			len(message) - 1 - message[::-1].find("}")
		)
		parsed_mode = (
			message[last_closing_bracker_index + 1 :].strip().lower()
		)
		message = message[: last_closing_bracker_index + 1]

		if parsed_mode:
			try:
				mode = WindowEnum(parsed_mode)
			except TypeError as err:
				msg = f"Unable to convert mode {parsed_mode} to type WindowEnum"
				raise commands.BadArgument(msg) from err

		decoded = await user_json.verify(
			self.bot, ctx, message, rank.formatter, member=ctx.author
		)

		_log.info(f"{decoded=}")

		gid = ctx.guild.id
		await db.rank.set_message(self.bot.pool, gid, decoded, mode=mode)

	@rank.command(name="demo")
	async def rank_demo(
		self, ctx: commands.Context, mode: WindowEnum = WindowEnum.SEASONAL
	):
		gid = ctx.guild.id
		payload = await db.rank.get_message(self.bot.pool, gid, mode=mode)
		decoded = payload

		member = ctx.author
		utility.deep_map(decoded, rank.formatter, member=member)

		content, embed, embeds = user_json.prepare(decoded)
		await ctx.send(content, embed=embed, embeds=embeds)

	@rank.command(name="raw")
	async def rank_raw(
		self, ctx: commands.Context, mode: WindowEnum = WindowEnum.SEASONAL
	):
		gid = ctx.guild.id
		payload = await db.rank.get_message(self.bot.pool, gid, mode=mode)
		await ctx.send(f"```{json.dumps(payload)}```")


async def setup(bot: commands.Bot):
	await bot.add_cog(Ranks(bot))
