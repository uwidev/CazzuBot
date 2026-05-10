"""Developer commands to run during operation."""

import logging
import os
import random
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

# from tinydb import Query, TinyDB


if TYPE_CHECKING:
	from main import CazzuBot


# import src.db_interface as dbi
# from src.serializers import TestEnum


_log = logging.getLogger(__name__)


class Dev(commands.Cog):
	def __init__(self, bot):
		self.bot: CazzuBot = bot
		# self.bot.tinydb = TinyDB("user.json")

	def cog_check(self, ctx):
		return ctx.author.id == self.bot.owner_id

	@commands.command()
	async def scrape(self, ctx):
		os.makedirs("emojis", exist_ok=True)

		for emoji in ctx.guild.emojis:
			ext = "gif" if emoji.animated else "png"
			await emoji.save(f"emojis/{emoji.name}_{emoji.id}.{ext}")

		await ctx.send(f"✅ Saved {len(ctx.guild.emojis)} emojis")

	@app_commands.command(name="foobar", description="cool description")
	async def command_test(self, interaction: discord.Interaction):
		"""test to see if command register"""

		view = DemoView()
		await interaction.response.send_message("hello world!", view=view)


class DemoView(discord.ui.View):
	def __init__(self):
		super().__init__(timeout=60)

	@discord.ui.button(
		label="Click me!", style=discord.ButtonStyle.primary, emoji="👍"
	)
	async def demo_buttom(
		self, interaction: discord.Interaction, button: discord.ui.Button
	):
		await interaction.response.send_message(
			"i can't believe you've done this"
		)

	@discord.ui.button(
		label="do not", style=discord.ButtonStyle.primary, emoji="👎"
	)
	async def demo_button2(
		self, interaction: discord.Interaction, button: discord.ui.Button
	):
		await interaction.response.send_message("no")

	@discord.ui.button(
		label="modal test", style=discord.ButtonStyle.primary, emoji="🎉"
	)
	async def demo_modal(
		self, interaction: discord.Interaction, button: discord.ui.Button
	):
		modal = DemoModal(10, 10)
		await interaction.response.send_modal(modal)


class DemoModal(
	discord.ui.Modal, title="Assign point(s) to last week's Cirno images"
):
	"""Create modal form with one input field, taking `max_vote` comma-separated ints.

	`upper`: Acceptable ints from 1 to `upper`; >= 1
	`max_vote`: Number of votes a user can put int; >=1
	"""

	def __init__(self, upper: int, max_vote: int = 1):
		super().__init__(timeout=300)

		if upper < 1:
			msg = f"Upper must be greater than 0, got {upper}"
			raise ValueError(msg)

		if max_vote < 1:
			msg = f"max_vote must be greater than 0, got {max_vote}"
			raise ValueError(msg)

		self.upper = upper
		self.max_vote = max_vote

		self.vote_input = discord.ui.TextInput(
			label=f"Max {self.max_vote} Votes",
			placeholder=f"Example: {', '.join(str(random.randint(1, self.upper + 1)) for _ in range(self.max_vote))}",
			style=discord.TextStyle.long,
		)

		self.add_item(self.vote_input)

	async def on_submit(self, interaction: discord.Interaction):
		"""Prase, validate, submit to database."""
		try:
			_log.info(self.vote_input.value)
			votes = await self.parse_votes(self.vote_input.value)
			errors = self.validate_votes(votes)

			if errors:
				await interaction.response.send_message(
					"❌ Invalid vote\n" + "\n".join(errors), ephemeral=True
				)
				return

			await self.store_values(votes)
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

	async def store_values(self, votes):
		pass


async def setup(bot: commands.Bot):
	await bot.add_cog(Dev(bot))
