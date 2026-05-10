import asyncio
import logging

import discord
import pendulum
from discord.ext import commands, tasks

from src import db
from src.utility import prepare_embed

_log = logging.getLogger(__name__)

FROG = "https://files.catbox.moe/qo7bkv.gif"
POGFROG = "https://files.catbox.moe/k5qvvd.gif"
BAKAPPLE = "https://files.catbox.moe/ogq9lq.gif"
BORED = "https://files.catbox.moe/0ex005.gif"


class Counter(commands.Cog):
	def __init__(self, bot):
		self.bot = bot

		self.wait_baka_expire.start()

	@commands.group()
	async def counter(self, ctx: commands.Context):
		"""Group counter command."""

	@commands.Cog.listener()
	async def on_raw_reaction_add(
		self, payload: discord.RawReactionActionEvent
	):
		"""Start timer to update counter if message is counter"""
		gid = payload.guild_id
		mid = payload.message_id

		counters = await db.counter.get_counters(self.bot.pool, gid)
		mids = [record.get("mid") for record in counters]

		if (
			payload.user_id == self.bot.user.id
			or not counters
			or mid not in mids
		):
			# ignore self
			# guild has not counters set
			# reaction was not on a counter message
			return

		counter = next(
			counter for counter in counters if counter.get("mid") == mid
		)
		cid = payload.channel_id
		ch = self.bot.get_channel(cid)
		msg: discord.Message = await ch.fetch_message(mid)
		total_reactions = sum(r.count for r in msg.reactions)

		# wait until no one reacts for a while before actually doing stuff
		prev_reactions = -1
		while prev_reactions != total_reactions:
			prev_reactions = total_reactions
			await asyncio.sleep(3)
			msg: discord.Message = await ch.fetch_message(mid)
			total_reactions = sum(r.count for r in msg.reactions)

		count_old = counter.get("count")
		total_reactions -= (
			1  # adjust reactions to take into account the bot's reaction
		)
		count_new = count_old + total_reactions

		await db.counter.update_count(self.bot.pool, mid, count_new)

		# prepare embed
		embed = prepare_embed(
			"Number of times people have touched the baka button",
			f"> {count_new}",
		)
		embed.set_thumbnail(url=BAKAPPLE)
		new_bakas_pairs = set()
		for reaction in msg.reactions:
			new_bakas_pairs.update(
				(user.id, user.display_name)
				for user in [user async for user in reaction.users()]
			)

		new_bakas_pairs = {
			p for p in new_bakas_pairs if p[0] != self.bot.user.id
		}

		# TODO: history per user; currently old users will stay on history
		# if new usrs keep reacting to it long past their last baka moment
		current_embed = msg.embeds[-1]
		old_bakas = (
			msg.embeds[-1]
			.footer.text.strip("There are no bakas as of recently...")
			.rstrip(" had recently done a baka!")
			.split(", ")
		)
		old_bakas = list(filter(lambda x: x, old_bakas))

		# combine current and new bakas
		final_bakas = set()
		final_bakas.update(old_bakas)
		final_bakas.update([pair[1] for pair in new_bakas_pairs])

		# TODO: use "and" for the last user when > 1 user reacted
		embed.set_footer(
			text=f"{', '.join(final_bakas)} had recently done a baka!",
			icon_url="https://files.catbox.moe/k5qvvd.gif",
		)

		# send embed, react
		await msg.edit(embed=embed)

		await msg.clear_reactions()
		await msg.add_reaction("<:cirnoHelp:695126168227151954>")

		# TODO: after some time, change to "... no bakas as of recently..."
		task = db.table.Task(
			["counter"],
			pendulum.now("UTC").add(hours=2),
			{
				'mid': mid,
				'cid': cid,
			},
		)
		await db.task.add(self.bot.pool, task)

	@tasks.loop(seconds=1)
	async def wait_baka_expire(self):
		records = await db.task.get(self.bot.pool, tag=['counter'])
		if not records:
			return

		now = pendulum.now("UTC")
		expired_counter_records = [
			item for item in records if item["run_at"] < now
		]

		for record in expired_counter_records:
			payload = record['payload']
			cid, mid = (payload['cid'], payload['mid'])
			cid = payload["cid"]
			ch = await self.bot.fetch_channel(cid)
			msg = discord.Message = await ch.fetch_message(mid)

			embed = msg.embeds[-1]
			embed.set_footer(text="There are no bakas as of recently...", icon_url="https://files.catbox.moe/qo7bkv.gif")
			embed.set_thumbnail(url=BORED)
			await msg.edit(embed=embed)

			await db.task.drop_one(self.bot.pool, record['id'])

	@counter.command(name="create")
	async def counter_create(self, ctx: commands.Context):
		"""Create message with counter and reaction."""
		# TODO: need some way to destroy counter in database,
		# define what conditions are needed to delete said entry
		embed = prepare_embed(
			"Number of times people have touched the baka button", "> 0"
		)
		embed.set_thumbnail(url="https://files.catbox.moe/ogq9lq.gif")
		embed.set_footer(
			text="There are no bakas as of recently...",
			icon_url="https://files.catbox.moe/qo7bkv.gif",
		)
		embed.set_thumbnail(url=BORED)
		msg = await ctx.send(embed=embed)
		await msg.add_reaction("<:cirnoHelp:695126168227151954>")

		gid = ctx.guild.id
		mid = msg.id
		payload = db.table.Counter(gid, mid)
		await db.counter.add(self.bot.pool, payload)


async def setup(bot: commands.Bot):
	await bot.add_cog(Counter(bot))
