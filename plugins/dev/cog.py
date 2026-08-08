"""Dev plugin extension — owner tools and plugin hotswap.

Ports v1's ``ext/owner.py`` + ``ext/hotswap.py`` + the useful bits of
``ext/dev.py``. The broken ``init_guild`` command is dropped (single guild,
no guild table to initialize).
"""

import logging
from pathlib import Path
from typing import cast

import hikari
import lightbulb

from cazzubot import levels
from cazzubot.bot import CazzuBot
from lightbulb.prefab import checks as prefab_checks

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()

_OWNER = prefab_checks.owner_only


def _bot(ctx: lightbulb.Context) -> CazzuBot:
    return cast(CazzuBot, ctx.client.app)


@loader.command()
class Owner(
    lightbulb.SlashCommand,
    name="owner",
    description="The bot owner check.",
    hooks=[_OWNER],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        _log.info("%s is the bot owner.", ctx.member or ctx.user)
        await ctx.respond(f"You are {(ctx.member or ctx.user).mention}!")


calc = lightbulb.Group("calc", "Helpers for level math.")


@calc.register
class CalcTo(
    lightbulb.SlashCommand,
    name="to",
    description="Exp required to get from level n-1 to n.",
    hooks=[_OWNER],
):
    n = lightbulb.integer("n", "The level")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond(f"{levels.exp_to_level(self.n):.2f}")


@calc.register
class CalcCum(
    lightbulb.SlashCommand,
    name="cum",
    description="Cumulative exp from level 0 to n.",
    hooks=[_OWNER],
):
    n = lightbulb.integer("n", "The level")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond(f"{levels.exp_to_level_cum(self.n):.2f}")


@loader.command()
class ArchiveEmojis(
    lightbulb.SlashCommand,
    name="archive_emojis",
    description="Save this guild's emojis to archives/{guild_id}/.",
    hooks=[_OWNER],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        guild = bot.guild
        if guild is None:
            await ctx.respond("Not in a guild.")
            return
        await ctx.respond("Saving server emoji's to disk...")
        archive_pth = Path("archives") / str(guild.id)
        archive_pth.mkdir(exist_ok=True, parents=True)
        for emoji in guild.get_emojis().values():
            data = await hikari.files.URL(str(emoji.url)).read()
            archive_pth.joinpath(emoji.name).write_bytes(data)
        await ctx.respond("Saved!")


@loader.command()
class Scrape(
    lightbulb.SlashCommand,
    name="scrape",
    description="Download every guild emoji into emojis/.",
    hooks=[_OWNER],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        guild = bot.guild
        if guild is None:
            await ctx.respond("Not in a guild.")
            return
        await ctx.respond("Scraping server emojis...")
        out = Path("emojis")
        out.mkdir(exist_ok=True)
        for emoji in guild.get_emojis().values():
            ext = "gif" if emoji.is_animated else "png"
            data = await hikari.files.URL(str(emoji.url)).read()
            out.joinpath(f"{emoji.name}_{emoji.id}.{ext}").write_bytes(
                data
            )
        await ctx.respond("Saved!")


# -- plugin hotswap ---------------------------------------------------------


cog = lightbulb.Group("cog", "Plugin hotswap.")


@cog.register
class PluginReload(
    lightbulb.SlashCommand,
    name="reload",
    description="Reload a loaded plugin.",
    hooks=[_OWNER],
):
    plugin_name = lightbulb.string("plugin_name", "The plugin to reload")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        if self.plugin_name not in [p.name for p in bot.plugins]:
            await ctx.respond(
                f"❌ plugin {self.plugin_name} is not loaded"
            )
            return
        await bot.reload_plugin(self.plugin_name)
        await ctx.respond(
            f"✅ plugin {self.plugin_name} has been reloaded"
        )


@cog.register
class PluginLoad(
    lightbulb.SlashCommand,
    name="load",
    description="Load a not-yet-loaded plugin.",
    hooks=[_OWNER],
):
    plugin_name = lightbulb.string("plugin_name", "The plugin to load")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        if self.plugin_name in [p.name for p in bot.plugins]:
            await ctx.respond(
                f"❌ plugin {self.plugin_name} is already loaded"
            )
            return
        await bot.load_plugin_by_name(self.plugin_name)
        await ctx.respond(f"✅ plugin {self.plugin_name} has been loaded")


@cog.register
class PluginUnload(
    lightbulb.SlashCommand,
    name="unload",
    description="Unload a loaded plugin.",
    hooks=[_OWNER],
):
    plugin_name = lightbulb.string("plugin_name", "The plugin to unload")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        bot = _bot(ctx)
        if self.plugin_name not in [p.name for p in bot.plugins]:
            await ctx.respond(
                f"❌ plugin {self.plugin_name} is not loaded"
            )
            return
        await bot.unload_plugin_by_name(self.plugin_name)
        await ctx.respond(
            f"✅ plugin {self.plugin_name} has been unloaded"
        )


loader.command(calc)
loader.command(cog)
