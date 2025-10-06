"""Event listener thing..."""

from discord.ext import commands

from main import CazzuBot


class Listener(commands.Cog):
	def __init__(self, bot: CazzuBot):
		self.bot = bot


async def setup(bot):
	await bot.add_cog(Listener(bot))
