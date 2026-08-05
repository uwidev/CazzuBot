"""Counter plugin — the "baka button" reaction counter.

Single-guild port of v1's ``ext/counter.py`` + ``src/db/counter.py``. A
registered counter message accumulates reactions; after activity settles the
count is updated, the footer shows who "did a baka", and a 2-hour expiry task
(tag ``counter``) resets the footer.
"""

import asyncio
import logging

import discord
import pendulum
from discord.ext import commands

from cazzubot import Plugin, utils

_log = logging.getLogger(__name__)

SCHEMA = [
	"""
	CREATE TABLE IF NOT EXISTS counter (
		mid   INTEGER PRIMARY KEY,
		count INTEGER NOT NULL DEFAULT 0
	)
	""",
]

FROG = "https://files.catbox.moe/qo7bkv.gif"
POGFROG = "https://files.catbox.moe/k5qvvd.gif"
BAKAPPLE = "https://files.catbox.moe/ogq9lq.gif"
BORED = "https://files.catbox.moe/0ex005.gif"
CIRNO_HELP = "<:cirnoHelp:695126168227151954>"

NO_BAKAS_TEXT = "There are no bakas as of recently..."


async def on_counter_expire(bot, payload: dict) -> None:
	"""Scheduler handler for tag ``counter`` — reset the embed footer."""
	cid, mid = payload["cid"], payload["mid"]
	channel = bot.get_channel(cid)
	if channel is None:
		return
	try:
		msg = await channel.fetch_message(mid)
	except discord.NotFound:
		return

	embed = msg.embeds[-1]
	embed.set_footer(text=NO_BAKAS_TEXT, icon_url=FROG)
	embed.set_thumbnail(url=BORED)
	await msg.edit(embed=embed)


class CounterCog(commands.Cog):
	"""Baka button counter."""

	def __init__(self, bot) -> None:
		self.bot = bot
		self._locks: dict[int, asyncio.Lock] = {}

	@commands.group()
	async def counter(self, ctx: commands.Context) -> None:
		"""Group counter command."""

	@commands.Cog.listener()
	async def on_raw_reaction_add(
		self, payload: discord.RawReactionActionEvent
	) -> None:
		"""Update the counter when someone reacts to a counter message."""
		if payload.user_id == self.bot.user.id:
			return

		row = await self.bot.db.fetchone(
			"SELECT * FROM counter WHERE mid = ?", payload.message_id
		)
		if row is None:
			return

		# one settle-loop per counter message at a time
		lock = self._locks.setdefault(payload.message_id, asyncio.Lock())
		async with lock:
			# re-read under the lock so concurrent batches don't lose counts
			row = await self.bot.db.fetchone(
				"SELECT * FROM counter WHERE mid = ?", payload.message_id
			)
			if row is None:
				return
			await self._process_counter(payload, row)

	async def _process_counter(
		self,
		payload: discord.RawReactionActionEvent,
		row: dict,
	) -> None:
		channel = self.bot.get_channel(payload.channel_id)
		if channel is None:
			return
		try:
			msg = await channel.fetch_message(payload.message_id)
		except discord.NotFound:
			return
		total_reactions = sum(r.count for r in msg.reactions)

		# wait until no one reacts for a while before updating
		prev_reactions = -1
		while prev_reactions != total_reactions:
			prev_reactions = total_reactions
			await asyncio.sleep(3)
			msg = await channel.fetch_message(payload.message_id)
			total_reactions = sum(r.count for r in msg.reactions)

		count_new = (
			row["count"] + total_reactions - 1
		)  # minus bot's reaction
		await self.bot.db.execute(
			"UPDATE counter SET count = ? WHERE mid = ?",
			count_new,
			payload.message_id,
		)

		embed = utils.prepare_embed(
			"Number of times people have touched the baka button",
			f"> {count_new}",
		)
		embed.set_thumbnail(url=BAKAPPLE)

		new_bakas = set()
		for reaction in msg.reactions:
			async for user in reaction.users():
				if user.id != self.bot.user.id:
					new_bakas.add((user.id, user.display_name))

		# carry over previous bakas from the embed footer
		footer = msg.embeds[-1].footer.text or ""
		old_bakas = (
			footer.removeprefix(NO_BAKAS_TEXT)
			.rstrip(" had recently done a baka!")
			.split(", ")
		)
		old_bakas = {b for b in old_bakas if b}
		final_bakas = old_bakas | {name for _, name in new_bakas}

		embed.set_footer(
			text=f"{', '.join(final_bakas)} had recently done a baka!",
			icon_url=POGFROG,
		)

		await msg.edit(embed=embed)
		await msg.clear_reactions()
		await msg.add_reaction(CIRNO_HELP)

		await self.bot.scheduler.add(
			"counter",
			pendulum.now("UTC").add(hours=2),
			{"mid": payload.message_id, "cid": payload.channel_id},
		)

	@counter.command(name="create")
	async def counter_create(self, ctx: commands.Context) -> None:
		"""Create the baka counter message in this channel."""
		embed = utils.prepare_embed(
			"Number of times people have touched the baka button", "> 0"
		)
		embed.set_thumbnail(url=BAKAPPLE)
		embed.set_footer(text=NO_BAKAS_TEXT, icon_url=FROG)
		msg = await ctx.send(embed=embed)
		await msg.add_reaction(CIRNO_HELP)
		await self.bot.db.execute(
			"INSERT OR IGNORE INTO counter (mid, count) VALUES (?, 0)",
			msg.id,
		)
		await ctx.message.add_reaction("👍")


class CounterPlugin(Plugin):
	name = "counter"
	schema = SCHEMA
	cogs = [CounterCog]
	scheduled = {"counter": on_counter_expire}


plugin = CounterPlugin()
