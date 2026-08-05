"""Levels plugin — level-up message config + the level-up pipeline.

Single-guild port of v1's ``ext/level.py`` + ``src/level.py``. The message
exp pipeline (in the experience plugin) calls ``handle_level_up``.
"""

import logging

import discord
from discord.ext import commands

from cazzubot import templates, utils

_log = logging.getLogger(__name__)

MESSAGE_KEY = "level.message"


def formatter(
	s: str,
	*,
	member: discord.Member,
	level_old: int | None = None,
	level_new: int | None = None,
) -> str:
	"""Placeholders: {avatar} {name} {mention} {id} {level_old} {level_new}"""
	return s.format(
		avatar=member.display_avatar.url,
		name=member.display_name,
		mention=member.mention,
		id=member.id,
		level_old=level_old,
		level_new=level_new,
	)


async def handle_level_up(
	bot,
	message: discord.Message,
	level: utils.OldNew,
	*,
	delete_after: int = 0,
) -> None:
	"""Send the level-up message when a member levels up (unless ranked up)."""
	if level.new <= level.old:
		return

	from plugins.ranks.logic import is_ranked_up

	if await is_ranked_up(bot, level):
		return  # rank up trumps level up

	quiets: list[int] = await bot.settings.get("level.quiet", []) or []
	if message.channel.id in quiets:
		await message.add_reaction("🎉")
		return

	msg_json = await bot.settings.get(MESSAGE_KEY)
	if not msg_json:
		return

	utils.deep_map(
		msg_json,
		formatter,
		member=message.author,
		level_old=level.old,
		level_new=level.new,
	)
	content, embed, embeds = templates.prepare(msg_json)
	await message.channel.send(
		content, embed=embed, embeds=embeds, delete_after=delete_after
	)


class LevelsCog(commands.Cog):
	"""Configure the level-up message."""

	def __init__(self, bot) -> None:
		self.bot = bot

	@commands.group(
		name="level", aliases=["lvl"], invoke_without_command=True
	)
	@commands.has_permissions(administrator=True)
	async def level(self, ctx: commands.Context) -> None:
		pass

	@level.command(name="set", aliases=["msg"])
	async def level_set(
		self, ctx: commands.Context, *, message: str
	) -> None:
		"""Set the level-up message JSON."""
		decoded = await templates.verify(
			ctx, message, formatter, member=ctx.author
		)
		await self.bot.settings.set(MESSAGE_KEY, decoded)
		await ctx.message.add_reaction("👍")

	@level.command(name="demo")
	async def level_demo(self, ctx: commands.Context) -> None:
		"""Preview the level-up message as yourself."""
		msg_json = await self.bot.settings.get(MESSAGE_KEY)
		if not msg_json:
			await ctx.send("No level-up message has been set.")
			return
		utils.deep_map(
			msg_json,
			formatter,
			member=ctx.author,
			level_old=1,
			level_new=2,
		)
		content, embed, embeds = templates.prepare(msg_json)
		await ctx.send(content, embed=embed, embeds=embeds)

	@level.command(name="raw")
	async def level_raw(self, ctx: commands.Context) -> None:
		"""Dump the raw stored level-up message JSON."""
		import json

		msg_json = await self.bot.settings.get(MESSAGE_KEY)
		await ctx.send(f"```{json.dumps(msg_json, indent=2)}```")
