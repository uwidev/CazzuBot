"""Debug access for owner."""

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from discord.ext import commands

from src import db, levels_helper

if TYPE_CHECKING:
	from main import CazzuBot


_log = logging.getLogger(__name__)


class Owner(commands.Cog):
	def __init__(self, bot):
		self.bot: CazzuBot = bot

	def cog_check(self, ctx):
		return ctx.author.id == self.bot.owner_id

	async def cog_after_invoke(self, ctx: commands.Context):
		if ctx.command_failed:
			await ctx.message.add_reaction("❌")
		# else:
		# await ctx.message.add_reaction("✅")

	@commands.command()
	async def owner(self, ctx: commands.Context):
		_log.info("%s is the bot owner.", ctx.author)

	@commands.command()
	async def init_guild(self, ctx: commands.Context):
		await db.guild.add(self.bot.pool, db.GuildSchema(ctx.guild.id))

	@commands.group()
	async def calc(self, ctx: commands.Context):
		"""Helper for calculating all things related to level."""

	@calc.command(name="to")
	async def calc_to(self, ctx: commands.Context, n: int):
		"""Calculate the exp required to get from n-1 to n."""
		res = levels_helper.exp_to_level(n)
		await ctx.reply(f"{res:.2f}")

	@calc.command(name="cum")
	async def calc_cum(self, ctx: commands.Context, n: int):
		"""Calculate the exp required to get from 0 to n."""
		res = levels_helper.exp_to_level_cum(n)
		await ctx.reply(f"{res:.2f}")

	@commands.command()
	async def archive_emojis(self, ctx: commands.Context):
		"""Save this guild's emojis to local files."""
		await ctx.send("Saving server emoji's to disk...")

		guild = ctx.guild
		emojis = guild.emojis

		# archives path based on docker volume mount
		archive_pth = Path("/usr/src/app/archives") / str(guild.id)
		archive_pth.mkdir(exist_ok=True, parents=True)

		_log.info(f"emojis will be saved to {archive_pth.resolve()}")

		for emoji in emojis:
			name = emoji.name
			save_to = archive_pth / name
			with save_to as fp:
				await emoji.save(save_to)

		await ctx.send("Saved!")


async def setup(bot: commands.Bot):
	await bot.add_cog(Owner(bot))
