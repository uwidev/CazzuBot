"""General commands that can be used by everyone."""

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

if TYPE_CHECKING:
	from main import CazzuBot


class Member(commands.Cog):
	def __init__(self, bot):
		self.bot: CazzuBot = bot

	@commands.command()
	async def hashiresoriyo(self, ctx):
		"""Gives you a jolly Saber."""
		await ctx.send("https://www.youtube.com/watch?v=dQ_d_VKrFgM")

	@commands.command()
	async def info(
		self, ctx: commands.Context, *, member: discord.Member = None
	):
		"""Provides you with basic user information."""
		if not member:
			member = ctx.author
		fmt = "{0} joined on {0.joined_at} and has {1} roles"
		await ctx.send(fmt.format(member, len(member.roles)))

	@commands.command()
	async def noot(self, ctx):
		"""Noot noot!."""
		await ctx.send("NOOT NOOT")

	@commands.command()
	async def ping(self, ctx):
		await ctx.send(
			":ping_pong: Pong! {}ms".format(
				str(self.bot.latency * 1000)[0:6]
			)
		)


async def setup(bot):
	await bot.add_cog(Member(bot))
