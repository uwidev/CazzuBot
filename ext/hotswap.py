"""Allows the hotswapping of extensions/cogs."""

import logging
import os

from discord.ext import commands


_log = logging.getLogger(__name__)


class HotSwap(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.group()
    async def cog(self, ctx: commands.Context):
        pass

    @cog.command()
    async def reload(self, ctx, *, ext_name):
        ext = f"{self.bot.ext_path}.{ext_name}"
        if ext not in self.bot.extensions:
            await ctx.send(f"❌ cog {ext_name} does not exist")

        try:
            await self.bot.reload_extension(ext)
            await ctx.send(f"✅ cog {ext_name} has been reloaded")
        except (
            commands.ExtensionNotLoaded,
            commands.ExtensionNotFound,
            commands.NoEntryPointError,
            commands.ExtensionFailed,
        ) as err:
            _log.error(err)

    @cog.command()
    async def load(self, ctx, ext_name):
        extensions = os.listdir(self.bot.ext_path)

        if ext_name not in map(lambda x: x[:-3], extensions):
            await ctx.send(f"❌ cog {ext_name} does not exist")
            return

        try:
            await self.bot.load_extension(f"{self.bot.ext_path}.{ext_name}")
            await ctx.send(f"✅ cog {ext_name} has been loaded")
        except (
            commands.ExtensionNotFound,
            commands.ExtensionAlreadyLoaded,
            commands.NoEntryPointError,
            commands.ExtensionFailed,
        ) as err:
            _log.error(err)

    @cog.command()
    async def unload(self, ctx, ext_name):
        ext = f"{self.bot.ext_path}.{ext_name}"

        if ext not in self.bot.extensions:
            await ctx.send(f"❌ cog {ext_name} wasn't loaded to begin with!")
            return

        extensions = os.listdir(self.bot.ext_path)
        if ext_name + ".py" not in extensions:
            await ctx.send(f"❌ cog {ext_name} does not exist")
            return

        try:
            await self.bot.unload_extension(f"{self.bot.ext_path}.{ext_name}")
            await ctx.send(f"✅ cog {ext_name} has been unloaded")
        except (commands.ExtensionNotFound, commands.ExtensionNotLoaded) as err:
            _log.error(err)


async def setup(bot: commands.Bot):
    await bot.add_cog(HotSwap(bot))
