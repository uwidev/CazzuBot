"""Dev plugin extension — owner tools and plugin hotswap.

Ports v1's ``ext/owner.py`` + ``ext/hotswap.py`` + the useful bits of
``ext/dev.py``. The broken ``init_guild`` command is dropped (single guild,
no guild table to initialize).
"""

import logging
from pathlib import Path

import hikari
import lightbulb

from cazzubot import levels, utils
from cazzubot.bot import CazzuBot
from cazzubot.errors import UserInputError
from cazzubot.plugin import discover_plugins

_log = logging.getLogger(__name__)

loader = lightbulb.Loader()


def _plugin_names(bot: CazzuBot) -> list[str]:
    """Loaded plugin names, in order."""
    return [p.name for p in bot.plugins]


async def _download_emojis(
    guild: hikari.GatewayGuild, out: Path, *, with_id: bool = False
) -> None:
    """Download every guild emoji into ``out`` (id-suffixed when asked)."""
    out.mkdir(exist_ok=True, parents=True)
    for emoji in guild.get_emojis().values():
        ext = "gif" if emoji.is_animated else "png"
        name = f"{emoji.name}_{emoji.id}.{ext}" if with_id else emoji.name
        data = await hikari.files.URL(str(emoji.url)).read()
        out.joinpath(name).write_bytes(data)


@loader.command()
class Owner(
    lightbulb.SlashCommand,
    name="owner",
    description="The bot owner check.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
    hooks=[utils.OWNER_ONLY],
):
    """Report whether the invoker is the bot owner."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Log and confirm the invoker is the owner."""
        _log.info("%s is the bot owner.", ctx.member or ctx.user)
        await ctx.respond(f"You are {(ctx.member or ctx.user).mention}!")


calc = lightbulb.Group(
    "calc",
    "Helpers for level math.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)


@calc.register
class CalcTo(
    lightbulb.SlashCommand,
    name="to",
    description="Exp required to get from level n-1 to n.",
    hooks=[utils.OWNER_ONLY],
):
    """Show the exp required to reach level ``n``."""

    n = lightbulb.integer("n", "The level")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Respond with the per-level exp cost."""
        await ctx.respond(f"{levels.exp_for_level(self.n):.2f}")


@calc.register
class CalcCum(
    lightbulb.SlashCommand,
    name="cum",
    description="Cumulative exp from level 0 to n.",
    hooks=[utils.OWNER_ONLY],
):
    """Show the cumulative exp through level ``n``."""

    n = lightbulb.integer("n", "The level")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Respond with the cumulative exp total."""
        await ctx.respond(f"{levels.exp_to_level_cum(self.n):.2f}")


@loader.command()
class ArchiveEmojis(
    lightbulb.SlashCommand,
    name="archive_emojis",
    description="Save this guild's emojis to archives/{guild_id}/.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
    hooks=[utils.OWNER_ONLY],
):
    """Save the guild's emojis to ``archives/{guild_id}/``."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Download every guild emoji into the archives folder."""
        bot = utils.bot_from(ctx)
        guild = bot.guild
        if guild is None:
            await ctx.respond("Not in a guild.")
            return
        await ctx.respond("Saving server emoji's to disk...")
        await _download_emojis(guild, Path("archives") / str(guild.id))
        await ctx.respond("Saved!")


@loader.command()
class Scrape(
    lightbulb.SlashCommand,
    name="scrape",
    description="Download every guild emoji into emojis/.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
    hooks=[utils.OWNER_ONLY],
):
    """Download every guild emoji into ``emojis/``."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Download each guild emoji id-suffixed into ``emojis/``."""
        bot = utils.bot_from(ctx)
        guild = bot.guild
        if guild is None:
            await ctx.respond("Not in a guild.")
            return
        await ctx.respond("Scraping server emojis...")
        await _download_emojis(guild, Path("emojis"), with_id=True)
        await ctx.respond("Saved!")


# -- plugin hotswap ---------------------------------------------------------


plugin_group = lightbulb.Group(
    "plugin",
    "Plugin hotswap.",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)


@plugin_group.register
class PluginReload(
    lightbulb.SlashCommand,
    name="reload",
    description="Reload a loaded plugin.",
    hooks=[utils.OWNER_ONLY],
):
    """Reload a loaded plugin (and its loaded dependents)."""

    plugin_name = lightbulb.string("plugin_name", "The plugin to reload")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Reload the named plugin and report what was reloaded."""
        bot = utils.bot_from(ctx)
        if self.plugin_name not in _plugin_names(bot):
            await ctx.respond(
                f"❌ plugin {self.plugin_name} is not loaded"
            )
            return
        # a provider reload also reloads its loaded dependents — report the
        # whole affected set (dependency order) so the owner sees the blast
        affected = bot.affected_by_unload(self.plugin_name)
        await bot.reload_plugin(self.plugin_name)
        if len(affected) == 1:
            await ctx.respond(
                f"✅ plugin {self.plugin_name} has been reloaded"
            )
        else:
            await ctx.respond("✅ reloaded " + ", ".join(affected[::-1]))


@plugin_group.register
class PluginLoad(
    lightbulb.SlashCommand,
    name="load",
    description="Load a not-yet-loaded plugin.",
    hooks=[utils.OWNER_ONLY],
):
    """Load a not-yet-loaded plugin."""

    plugin_name = lightbulb.string("plugin_name", "The plugin to load")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Load the named plugin."""
        bot = utils.bot_from(ctx)
        if self.plugin_name in _plugin_names(bot):
            await ctx.respond(
                f"❌ plugin {self.plugin_name} is already loaded"
            )
            return
        await bot.load_plugin_by_name(self.plugin_name)
        await ctx.respond(f"✅ plugin {self.plugin_name} has been loaded")


@plugin_group.register
class PluginUnload(
    lightbulb.SlashCommand,
    name="unload",
    description="Unload a loaded plugin.",
    hooks=[utils.OWNER_ONLY],
):
    """Unload a loaded plugin (and its loaded dependents)."""

    plugin_name = lightbulb.string("plugin_name", "The plugin to unload")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Unload the named plugin."""
        bot = utils.bot_from(ctx)
        if self.plugin_name not in _plugin_names(bot):
            await ctx.respond(
                f"❌ plugin {self.plugin_name} is not loaded"
            )
            return
        await bot.unload_plugin_by_name(self.plugin_name)
        await ctx.respond(
            f"✅ plugin {self.plugin_name} has been unloaded"
        )


@plugin_group.register
class PluginEnable(
    lightbulb.SlashCommand,
    name="enable",
    description="Enable a plugin (persisted) and load it with its dependencies.",
    hooks=[utils.OWNER_ONLY],
):
    """Enable a plugin (persisted) and load it with its dependencies."""

    plugin_name = lightbulb.string("plugin_name", "The plugin to enable")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Enable and load the named plugin."""
        bot = utils.bot_from(ctx)
        try:
            loaded = await bot.enable_plugin(self.plugin_name)
        except UserInputError as err:
            await ctx.respond(f"❌ {err}")
            return
        if not loaded:
            await ctx.respond(
                f"✅ plugin {self.plugin_name} is enabled (already loaded)"
            )
        else:
            await ctx.respond(
                "✅ enabled and loaded: " + ", ".join(loaded)
            )


@plugin_group.register
class PluginDisable(
    lightbulb.SlashCommand,
    name="disable",
    description="Disable a plugin (persisted) and unload it with its dependents.",
    hooks=[utils.OWNER_ONLY],
):
    """Disable a plugin (persisted) and unload it with its dependents."""

    plugin_name = lightbulb.string("plugin_name", "The plugin to disable")

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Disable and unload the named plugin."""
        bot = utils.bot_from(ctx)
        try:
            unloaded = await bot.disable_plugin(self.plugin_name)
        except UserInputError as err:
            await ctx.respond(f"❌ {err}")
            return
        if not unloaded:
            await ctx.respond(
                f"✅ plugin {self.plugin_name} is disabled "
                "(was not loaded)"
            )
        else:
            await ctx.respond(
                "✅ disabled and unloaded: " + ", ".join(unloaded)
            )


@plugin_group.register
class PluginList(
    lightbulb.SlashCommand,
    name="list",
    description="Show every plugin with its loaded/disabled state.",
    hooks=[utils.OWNER_ONLY],
):
    """List every plugin with its loaded/disabled state."""

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Show the per-plugin loaded/disabled status."""
        bot = utils.bot_from(ctx)
        loaded = {p.name for p in bot.plugins}
        plugins = discover_plugins(bot.plugins_dir)
        disabled = {
            p.name for p in plugins if not await bot.plugin_enabled(p)
        }
        lines = []
        for plugin in sorted(plugins, key=lambda p: p.name):
            if plugin.name in loaded:
                lines.append(f"✅ {plugin.name}")
            elif plugin.name in disabled:
                lines.append(f"⛔ {plugin.name} (disabled)")
            else:
                lines.append(f"⬜ {plugin.name} (not loaded)")
        await ctx.respond("\n".join(lines) or "no plugins")


loader.command(calc)
loader.command(plugin_group)
