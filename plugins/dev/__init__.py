"""Dev plugin — owner tools and plugin hotswap.

Ports v1's ``ext/owner.py`` + ``ext/hotswap.py`` + the useful bits of
``ext/dev.py``. The broken ``init_guild`` command is dropped (single guild,
no guild table to initialize).
"""

import logging
from pathlib import Path

from discord.ext import commands

from cazzubot import Plugin, levels

_log = logging.getLogger(__name__)


class DevCog(commands.Cog):
	"""Owner-only tools."""

	def __init__(self, bot) -> None:
		self.bot = bot

	async def cog_check(self, ctx: commands.Context) -> bool:
		return ctx.author.id == self.bot.owner_id

	@commands.hybrid_command()
	async def owner(self, ctx: commands.Context) -> None:
		_log.info("%s is the bot owner.", ctx.author)
		await ctx.send(f"You are {ctx.author.mention}!")

	@commands.hybrid_group()
	async def calc(self, ctx: commands.Context) -> None:
		"""Helpers for level math."""

	@calc.command(name="to")
	async def calc_to(self, ctx: commands.Context, n: int) -> None:
		"""Exp required to get from level n-1 to n."""
		await ctx.reply(f"{levels.exp_to_level(n):.2f}")

	@calc.command(name="cum")
	async def calc_cum(self, ctx: commands.Context, n: int) -> None:
		"""Cumulative exp from level 0 to n."""
		await ctx.reply(f"{levels.exp_to_level_cum(n):.2f}")

	@commands.hybrid_command()
	async def archive_emojis(self, ctx: commands.Context) -> None:
		"""Save this guild's emojis to archives/{guild_id}/."""
		await ctx.send("Saving server emoji's to disk...")
		archive_pth = Path("archives") / str(ctx.guild.id)
		archive_pth.mkdir(exist_ok=True, parents=True)
		for emoji in ctx.guild.emojis:
			await emoji.save(archive_pth / emoji.name)
		await ctx.send("Saved!")

	@commands.hybrid_command()
	async def scrape(self, ctx: commands.Context) -> None:
		"""Download every guild emoji into emojis/."""
		await ctx.send("Scraping server emojis...")
		out = Path("emojis")
		out.mkdir(exist_ok=True)
		for emoji in ctx.guild.emojis:
			ext = "gif" if emoji.animated else "png"
			await emoji.save(out / f"{emoji.name}_{emoji.id}.{ext}")
		await ctx.send("Saved!")


class HotswapCog(commands.Cog):
	"""Load/reload/unload plugins at runtime."""

	def __init__(self, bot) -> None:
		self.bot = bot

	async def cog_check(self, ctx: commands.Context) -> bool:
		return ctx.author.id == self.bot.owner_id

	@commands.hybrid_group()
	async def cog(self, ctx: commands.Context) -> None:
		"""Plugin hotswap."""

	@cog.command(name="reload")
	async def plugin_reload(
		self, ctx: commands.Context, *, plugin_name: str
	) -> None:
		if plugin_name not in self.bot._plugin_by_name:
			await ctx.send(f"❌ plugin {plugin_name} is not loaded")
			return
		await self.bot.reload_plugin(plugin_name)
		await ctx.send(f"✅ plugin {plugin_name} has been reloaded")

	@cog.command(name="load")
	async def plugin_load(
		self, ctx: commands.Context, *, plugin_name: str
	) -> None:
		if plugin_name in self.bot._plugin_by_name:
			await ctx.send(f"❌ plugin {plugin_name} is already loaded")
			return
		await self.bot.load_plugin_by_name(plugin_name)
		await ctx.send(f"✅ plugin {plugin_name} has been loaded")

	@cog.command(name="unload")
	async def plugin_unload(
		self, ctx: commands.Context, *, plugin_name: str
	) -> None:
		if plugin_name not in self.bot._plugin_by_name:
			await ctx.send(f"❌ plugin {plugin_name} is not loaded")
			return
		await self.bot.unload_plugin_by_name(plugin_name)
		await ctx.send(f"✅ plugin {plugin_name} has been unloaded")


class DevPlugin(Plugin):
	name = "dev"
	cogs = [DevCog, HotswapCog]


plugin = DevPlugin()
