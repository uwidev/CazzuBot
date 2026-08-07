"""The bot itself.

``CazzuBot`` owns the shared services (db, settings, scheduler, plugins) and
runs the plugin lifecycle. Plugins reach everything through ``self.bot``.
"""

import importlib
import logging
import sys

import discord
from discord.ext import commands
from typing_extensions import override

from cazzubot.config import Config
from cazzubot.db import Database, SchemaMismatchError
from cazzubot.plugin import Plugin, discover_plugins
from cazzubot.scheduler import Scheduler
from cazzubot.settings import Settings

_log = logging.getLogger(__name__)


class CazzuBot(commands.Bot):
    """Single-guild discord bot with a plugin architecture."""

    def __init__(
        self,
        config: Config,
        *,
        plugins_dir: str = "plugins",
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=config.prefix,
            intents=intents,
            owner_id=config.owner_id,
        )

        self.config = config
        self.plugins_dir = plugins_dir

        self.db = Database(config.db_path)
        self.settings = Settings(self.db)
        self.scheduler = Scheduler(self)

        self.plugins: list[Plugin] = []
        self._plugin_by_name: dict[str, Plugin] = {}

        if config.debug:
            self.add_check(CazzuBot.is_debug_mode)

    @property
    def guild(self) -> discord.Guild | None:
        """The one guild this bot serves."""
        return self.get_guild(self.config.guild_id)

    @staticmethod
    async def is_debug_mode(ctx: "commands.Context[CazzuBot]") -> bool:
        """In debug mode only the owner (and configured debug users) may run."""
        bot = ctx.bot
        if ctx.author.id in bot.config.debug_users:
            return True
        return await bot.is_owner(ctx.author)

    # -- plugin lifecycle --------------------------------------------------

    def _plugin_module(self, name: str):
        return importlib.import_module(f"{self.plugins_dir}.{name}")

    async def load_plugin(
        self, plugin: Plugin, *, run_hooks: bool = True
    ) -> None:
        """Apply a plugin's schema, cogs and scheduled handlers."""
        await self.db.run_schema(plugin.schema)
        for tag, handler in plugin.scheduled.items():
            self.scheduler.register(tag, handler)
        for cog in plugin.cogs:
            await self.add_cog(cog(self))
        self.plugins.append(plugin)
        self._plugin_by_name[plugin.name] = plugin
        if run_hooks:
            await plugin.on_load(self)
        _log.info("loaded plugin: %s", plugin.name)

    async def unload_plugin(self, plugin: Plugin) -> None:
        """Remove a plugin's cogs, handlers and run its teardown hook."""
        await plugin.on_unload(self)
        for tag in plugin.scheduled:
            self.scheduler.handlers.pop(tag, None)
        for cog in plugin.cogs:
            await self.remove_cog(cog.__cog_name__)
        self.plugins.remove(plugin)
        self._plugin_by_name.pop(plugin.name, None)
        _log.info("unloaded plugin: %s", plugin.name)

    async def reload_plugin(self, name: str) -> Plugin:
        """Re-import a plugin (including its submodules) and swap in new cogs."""
        old = self._plugin_by_name.get(name)
        if old is not None:
            await self.unload_plugin(old)

        # purge the whole plugins.<name> module tree so importlib.reload
        # actually picks up changes in cog.py / db.py / logic.py
        prefix = f"{self.plugins_dir}.{name}"
        for mod_name in list(sys.modules):
            if mod_name == prefix or mod_name.startswith(prefix + "."):
                del sys.modules[mod_name]

        module = importlib.import_module(prefix)
        plugin = module.plugin
        if not isinstance(plugin, Plugin):
            raise commands.BadArgument(f"{name} is not a plugin package")
        await self.load_plugin(plugin)
        return plugin

    async def load_plugin_by_name(self, name: str) -> Plugin:
        """Import and load a plugin that isn't currently loaded."""
        module = importlib.import_module(f"{self.plugins_dir}.{name}")
        plugin = getattr(module, "plugin", None)
        if not isinstance(plugin, Plugin):
            raise commands.BadArgument(f"{name} is not a plugin")
        await self.load_plugin(plugin)
        return plugin

    async def unload_plugin_by_name(self, name: str) -> None:
        """Unload a loaded plugin by name."""
        plugin = self._plugin_by_name.get(name)
        if plugin is None:
            raise commands.BadArgument(f"plugin {name} is not loaded")
        await self.unload_plugin(plugin)

    # -- bot lifecycle -----------------------------------------------------

    @override
    async def setup_hook(self) -> None:
        _log.info("connecting to database...")
        await self.db.connect()

        # core schema
        await self.db.run_schema(self.settings.schema)
        await self.db.run_schema(self.scheduler.schema)

        # discover and load plugins — two phases so any on_load hook can
        # depend on every plugin's schema/cogs being ready (no load order).
        plugins = discover_plugins(self.plugins_dir)
        if self.config.sandbox:
            allowed = {"poll", "board", "dev"}
            plugins = [p for p in plugins if p.name in allowed]
            _log.warning(
                "sandbox mode: loading %s", [p.name for p in plugins]
            )

        for plugin in plugins:
            await self.load_plugin(plugin, run_hooks=False)

        # boot-time schema guard: every table the DDL defines must exist in
        # the database exactly as defined. Terminate rather than let the
        # on-disk schema silently diverge (extra DB tables are allowed).
        statements = [*self.settings.schema, *self.scheduler.schema]
        for plugin in plugins:
            statements.extend(plugin.schema)
        try:
            await self.db.verify_schema(statements)
        except SchemaMismatchError as err:
            _log.critical(
                "database schema mismatch — refusing to boot:\n%s", err
            )
            raise SystemExit(1) from err

        for plugin in plugins:
            await plugin.on_load(self)

        # central task scheduler
        await self.scheduler.start()

    @override
    async def close(self) -> None:
        await self.scheduler.stop()
        for plugin in list(self.plugins):
            await self.unload_plugin(plugin)
        await self.db.close()
        await super().close()

    async def on_ready(self) -> None:
        if self.user is not None:
            _log.info("logged in as %s (%s)", self.user, self.user.id)
        if self.guild is None:
            _log.warning(
                "configured guild %s not found — commands will not work",
                self.config.guild_id,
            )
        try:
            await self.tree.sync()
        except discord.HTTPException:
            _log.exception("failed to sync command tree")

    @override
    async def on_command_error(
        self,
        ctx: "commands.Context[commands.Bot | commands.AutoShardedBot]",
        err: commands.CommandError,
        /,
    ) -> None:
        if isinstance(err, commands.BadArgument):
            await ctx.reply(str(err))
            return
        if isinstance(err, discord.Forbidden):
            return
        await super().on_command_error(ctx, err)
