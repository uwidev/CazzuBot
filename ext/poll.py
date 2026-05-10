"""Poll application commands."""

# TODO: poll results at the end

import logging
import random
from typing import TYPE_CHECKING

import discord
from asyncpg import Record
from discord import app_commands
from discord.ext import commands

from src import db, utility

# from tinydb import Query, TinyDB


if TYPE_CHECKING:
	from main import CazzuBot


# import src.db_interface as dbi
# from src.serializers import TestEnum


_log = logging.getLogger(__name__)

EMOJI_CLOSED = "https://files.catbox.moe/b67ajq.webp"
EMOJI_OPEN = "https://files.catbox.moe/xd4h7v.webp"
EMOJI_INBOX = "https://files.catbox.moe/3cy0by.webp"


class Poll(commands.Cog):
	def __init__(self, bot):
		self.bot: CazzuBot = bot

	def cog_check(self, ctx):
		"""Cog currently for testing purposes."""
		return ctx.author.id == self.bot.owner_id

	poll_group = app_commands.Group(
		name="poll", description="Poll management"
	)

	@poll_group.command(name="register", description="Register a poll.")
	@app_commands.describe(
		max_vote="Default total votes a user can submit",
	)
	async def poll_register(
		self,
		interaction: discord.Interaction,
		title: str,
		desc: str | None = None,
		max_vote: int = 1,
	):
		"""Poll the image board."""

		# create poll row in database
		gid = interaction.guild.id

		table_poll = db.table.Poll(gid, title, desc, max_vote)
		id = await db.poll.add_poll(self.bot.pool, table_poll)

		await interaction.response.send_message(
			f"Your poll has been registered!\nReference it with ID#{id}",
			ephemeral=True,
		)

	poll_item_group = app_commands.Group(
		parent=poll_group, name="item", description="Poll item management"
	)

	@poll_item_group.command(
		name="auto_populate",
		description="Generate N empty items to vote on.",
	)
	@app_commands.describe(
		n="Generate N items.", pid="Poll to generate N items on."
	)
	async def poll_item_auto_populate(
		self, interaction: discord.Interaction, pid: int, n: int
	):
		gid = interaction.guild.id
		await db.poll.add_items_dummy(self.bot.pool, gid, pid, n)
		await interaction.response.send_message(
			"👍 Items have been added.", ephemeral=True
		)

	@poll_group.command(
		name="send",
		description="Send the message containing the poll and allowing votes (if open).",
	)
	@app_commands.describe(
		poll_id="ID associated with the poll",
	)
	async def poll_send(
		self, interaction: discord.Interaction, poll_id: int
	):
		"""Create and send the message associated with the poll."""
		gid = interaction.guild.id

		# ensure poll with id exists
		poll_record = await db.poll.get_poll(self.bot.pool, gid, poll_id)
		if not poll_record:
			callback = f"❌ Poll ID#{poll_id} does not exist!"
			await interaction.response.send_message(callback, ephemeral=True)
			return

		# ensure poll has items
		items = await db.poll.get_items(self.bot.pool, gid, poll_id)
		if not items:
			callback = "❌ Poll has 0 items to vote on!"
			await interaction.response.send_message(callback, ephemeral=True)
			return

		title = poll_record.get("title")
		desc = poll_record.get("description")

		embed = utility.prepare_embed(title, desc)
		embed.set_footer(text=f"Poll ID#{poll_id}", icon_url=EMOJI_OPEN)

		view = PollView(self.bot, gid, poll_id)
		callback = await interaction.response.send_message(
			embed=embed, view=view
		)

		msg = await interaction.original_response()
		view.message = msg

		mid = msg.id
		await db.poll.set_mid(self.bot.pool, gid, poll_id, mid)

	@poll_group.command(
		name="open",
		description="Allow votes on a poll."
	)
	@app_commands.describe(
		poll_id="Poll ID to open. Message must have been sent."
	)
	async def poll_open(self, interaction: discord.Interaction, poll_id: int):
		gid = interaction.guild.id
		record = await db.poll.get_poll(self.bot.pool, gid, poll_id)

		# ensure mid exists
		mid = record.get('mid')
		if not mid:
			msg = f"❌ Message for poll ID#{poll_id} does not yet exist!"
			await interaction.reaction.send_message(msg)
			return

		# ensure message exists
		msg = await interaction.channel.fetch_message(mid)
		if not msg:
			msg = f"❌ Message for poll ID#{poll_id} no longer exists!"
			await interaction.reaction.send_message(msg)
			return

		await db.poll.open(self.bot.pool, gid, poll_id)


	@poll_group.command(
		name="stats",
		description="Show the current results from a poll.",
	)
	@app_commands.describe(
		poll_id="ID associated with the poll",
	)
	async def poll_stats(
		self, interaction: discord.Interaction, poll_id: int
	):
		gid = interaction.guild.id
		records = await db.poll.get_votes(self.bot.pool, gid, poll_id)
		stats = [tuple(record.values()) for record in records]

		# for this iteration, we lose track of description...
		
		# aggregate the individual votes into a iid:total
		aggregate = {}
		for iid, count, desc in stats:
			aggregate[iid] = aggregate.get(iid, 0) + count

		stats = list(aggregate.items())
		stats.sort(key=lambda x: x[1], reverse=True)
		total = sum((count for _, count in stats))
		await interaction.response.send_message(
			f"```{'Item':<16}{'Count':>8}{'Percent':>8}\n"
			+ "\n".join(
				f"{desc or item:<16}{count:>8}{count / total:>8.2%}"
				for item, count in stats[:min(10, len(stats))]
			)
			+ "```"
		)


class PollView(discord.ui.View):
	def __init__(self, bot, gid: int, poll_id: int):
		super().__init__(timeout=None)
		self.bot = bot
		self.gid = gid
		self.poll_id = poll_id
		self.message: discord.InteractionMessage | None = None

	# TODO: default voting closed
	# TODO: persistent views
	# TODO: allow closing/opening of votes
	@discord.ui.button(
		label="Vote", style=discord.ButtonStyle.primary, emoji="📥", disabled=False
	)
	async def vote(
		self, interaction: discord.Interaction, button: discord.ui.Button
	):
		poll_record = await db.poll.get_poll(
			self.bot.pool, self.gid, self.poll_id
		)
		items = await db.poll.get_items(
			self.bot.pool, self.gid, self.poll_id
		)
		modal = PollModal(self.bot, poll_record, items)
		await interaction.response.send_modal(modal)
	
	async def open(self):
		for child in self.children:
			if isinstance(child, discord.ui.Button) and child.label == "Voting Closed":
				child.disabled = False
				break

		if self.message:
			await self.message.edit(view=self)


# TODO: assign title dynamically
class PollModal(
	discord.ui.Modal, title="Assign vote(s) to last week's Cirno images"
):
	"""Create modal form with one input field, taking `max_vote` comma-separated ints.

	`upper`: Acceptable ints from 1 to `upper`; >= 1
	`max_vote`: Number of votes a user can put int; >=1
	"""

	def __init__(self, bot, poll_record, items):
		super().__init__(timeout=300)
		self.bot = bot
		self.poll_record: Record = poll_record
		self.items = items

		self.max_vote = poll_record.get("max_vote")
		self.upper = len(items)

		self.vote_input = discord.ui.TextInput(
			label=f"Max {self.max_vote} votes on items 1 to {self.upper}",
			placeholder=f"Comma-seperated items to vote on (e.g. \"{', '.join(str(random.randint(1, self.upper + 1)) for _ in range(self.max_vote))}\")",
			style=discord.TextStyle.long,
		)

		self.add_item(self.vote_input)

	async def on_submit(self, interaction: discord.Interaction):
		"""Prase, validate, submit to database."""
		try:
			votes = await self.parse_votes(self.vote_input.value)
			errors = self.validate_votes(votes)

			if errors:
				await interaction.response.send_message(
					"❌ Invalid vote\n" + "\n".join(errors), ephemeral=True
				)
				return

			# delete the user's previous votes on this poll
			gid = self.poll_record.get("gid")
			pid = self.poll_record.get("id")
			uid = interaction.user.id
			await db.poll.drop_user_on_poll(self.bot.pool, gid, pid, uid)

			# store value assuming all validations pass
			uid = interaction.user.id
			await self.store_values(uid, votes)
			await interaction.response.send_message(
				f"Your vote(s) of {votes} have been recorded.",
				ephemeral=True,
			)

		except (TypeError, ValueError) as e:
			await interaction.response.send_message(
				f"❌ Format error: {e}",
				ephemeral=True,
			)

	async def parse_votes(self, raw_input):
		"""Turn input into workable data structure."""
		votes = [vote.strip() for vote in raw_input.split(",") if vote]

		# edge case "-" captured by first clause, otherwise it would raise error on v[1:]
		not_numbers = [
			v
			for v in votes
			if not (v.isdigit() or (v[0] == "-" and v[1:].isdigit()))
		]
		if not_numbers:
			raise TypeError(f"Input is not a digit: {not_numbers}")

		# parsed nothing
		if not votes:
			raise ValueError("No votes entered")

		# turn into appropriate type
		votes = [int(v) for v in votes]

		return votes

	def validate_votes(self, votes: list[type[int]]):
		"""Validate data against poll criteria."""
		errors = []

		# out of range
		out_of_range = [
			v for v in votes if v not in range(1, self.upper + 1)
		]
		if out_of_range:
			errors.append(
				f"Numbers out of range (1-{self.upper}): {out_of_range}"
			)

		# too many votes
		if len(votes) > self.max_vote:
			errors.append(
				f"Too many votes (max {self.max_vote}): got {len(votes)}"
			)

		return errors

	async def store_values(self, uid, votes):
		gid: int = self.poll_record.get("gid")
		pid: int = self.poll_record.get("id")

		poll_votes = [
			db.table.PollVote(gid, pid, iid, uid) for iid in votes
		]

		await db.poll.add_votes(self.bot.pool, poll_votes)


async def setup(bot: commands.Bot):
	await bot.add_cog(Poll(bot))
