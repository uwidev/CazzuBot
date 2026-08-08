"""The bot itself.

``CazzuBot`` owns the shared services (db, settings, scheduler, plugins) and
runs the plugin lifecycle. Plugins reach everything through ``self.bot``.
"""

import asyncio
import importlib
import logging
import sys

import hikari
import lightbulb

from cazzubot.config import Config
from cazzubot.db import Database, SchemaMismatchError
from cazzubot.errors import UserInputError
from cazzubot.plugin import Plugin, discover_plugins
from cazzubot.scheduler import Scheduler
from cazzubot.settings import Settings

_log = logging.getLogger(__name__)


class _DebugModeBlocked(Exception):
    """Marker: a command was blocked by the debug-mode gate."""


class CazzuBot(hikari.GatewayBot):
    """Single-guild Discord bot with a plugin architecture."""

    def __init__(
        self,
        config: Config,
        *,
        plugins_dir: str = "plugins",
    ) -> None:
        intents = (
            hikari.Intents.ALL_UNPRIVILEGED
            | hikari.Intents.MESSAGE_CONTENT
            | hikari.Intents.GUILD_MEMBERS
        )
        super().__init__(config.token, intents=intents)

        self.config = config
        self.plugins_dir = plugins_dir

        self.db = Database(config.db_path)
        self.settings = Settings(self.db)
        self.scheduler = Scheduler(self)

        self.plugins: list[Plugin] = []
        self._plugin_by_name: dict[str, Plugin] = {}

        if config.debug:
            # debug gate: only the owner and configured debug users may run
            # commands; everyone else fails the CHECKS execution step.
            @lightbulb.hook(lightbulb.ExecutionSteps.CHECKS)
            def debug_gate(
                _pl: lightbulb.ExecutionPipeline,
                ctx: lightbulb.Context,
            ) -> None:
                member = ctx.member
                if (
                    member is not None
                    and member.id not in config.debug_users
                    and member.id != config.owner_id
                ):
                    raise _DebugModeBlocked()

            hooks = [debug_gate]
        else:
            hooks = []

        self.lightbulb = lightbulb.client_from_app(
            self,
            default_enabled_guilds=[config.guild_id],
            hooks=hooks,
        )
        self.lightbulb.error_handler(self._on_command_error)

        # startup must finish before lightbulb syncs guild commands, so the
        # StartingEvent handler is subscribed before the client's.
        self.subscribe(hikari.StartingEvent, self._on_starting)
        self.subscribe(hikari.StartedEvent, self._on_started)
        self.subscribe(
            hikari.GuildAvailableEvent, self._on_guild_available
        )
        self.subscribe(hikari.StoppingEvent, self._on_stopping)
        self.subscribe(hikari.StartedEvent, self.lightbulb.start)
        self.subscribe(hikari.StoppingEvent, self.lightbulb.stop)

    # -- bot lifecycle -----------------------------------------------------

    async def _on_starting(self, _event: hikari.StartingEvent) -> None:
        _log.info("connecting to database...")
        await self.db.connect()

        # core schema
        await self.db.run_schema(self.settings.schema)
        await self.db.run_schema(self.scheduler.schema)

        # discover and load plugins — two phases so any on_load hook can
        # depend on every plugin's schema/extensions being ready (no load
        # order).
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

    async def _on_started(self, _event: hikari.StartedEvent) -> None:
        me = self.get_me()
        if me is not None:
            _log.info("logged in as %s (%s)", me, me.id)
        if self.is_alive:
            # the guild dump lands right after StartedEvent; warn only once
            # it has had a moment to arrive (tests boot without a gateway,
            # so is_alive is False there and nothing is scheduled)
            asyncio.create_task(self._warn_if_guild_missing())

    async def _warn_if_guild_missing(self) -> None:
        await asyncio.sleep(2)
        if self.guild is None:
            _log.warning(
                "configured guild %s not found — commands will not work",
                self.config.guild_id,
            )

    async def _on_guild_available(
        self, event: hikari.GuildAvailableEvent
    ) -> None:
        """Run guild-dependent checks once the guild dump has landed.

        hikari dispatches ``StartedEvent`` before the buffered
        ``GuildAvailable`` events, so the cache is still empty inside
        ``_on_started``; anything that needs ``self.guild`` runs from
        here instead.
        """
        if event.guild_id == self.config.guild_id:
            _log.info("configured guild %s available", event.guild_id)

    async def _on_stopping(self, _event: hikari.StoppingEvent) -> None:
        await self.scheduler.stop()
        for plugin in list(self.plugins):
            await self.unload_plugin(plugin)
        await self.db.close()

    # -- error translation -------------------------------------------------

    async def _on_command_error(
        self,
        err: lightbulb.exceptions.ExecutionPipelineFailedException,
    ) -> bool:
        """Translate service/core errors into user-facing replies.

        Returns True when the error was handled; False lets lightbulb's
        default logging take over.
        """
        cause = err.__cause__
        if isinstance(cause, _DebugModeBlocked):
            return True
        if isinstance(cause, UserInputError):
            # service/core validation errors (see cazzubot/errors.py) are
            # not framework exceptions, so the pipeline wraps them
            ctx = err.context
            await ctx.respond(
                str(cause), flags=hikari.MessageFlag.EPHEMERAL
            )
            return True
        if isinstance(
            cause, lightbulb.exceptions.ConversionFailedException
        ):
            ctx = err.context
            await ctx.respond(
                str(cause), flags=hikari.MessageFlag.EPHEMERAL
            )
            return True
        if isinstance(cause, hikari.ForbiddenError):
            return True
        return False

    # -- plugin lifecycle --------------------------------------------------

    async def load_plugin(
        self, plugin: Plugin, *, run_hooks: bool = True
    ) -> None:
        """Apply a plugin's schema, extensions and scheduled handlers."""
        await self.db.run_schema(plugin.schema)
        for tag, handler in plugin.scheduled.items():
            self.scheduler.register(tag, handler)
        if plugin.extensions:
            await self.lightbulb.load_extensions(*plugin.extensions)
        self.plugins.append(plugin)
        self._plugin_by_name[plugin.name] = plugin
        if run_hooks:
            await plugin.on_load(self)
        _log.info("loaded plugin: %s", plugin.name)

    async def unload_plugin(self, plugin: Plugin) -> None:
        """Remove a plugin's extensions, handlers and run its teardown hook."""
        await plugin.on_unload(self)
        for tag in plugin.scheduled:
            self.scheduler.handlers.pop(tag, None)
        if plugin.extensions:
            await self.lightbulb.unload_extensions(*plugin.extensions)
        self.plugins.remove(plugin)
        self._plugin_by_name.pop(plugin.name, None)
        _log.info("unloaded plugin: %s", plugin.name)

    async def reload_plugin(self, name: str) -> Plugin:
        """Re-import a plugin (including its submodules) and swap in new
        extensions."""
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
            raise UserInputError(f"{name} is not a plugin package")
        await self.load_plugin(plugin)
        return plugin

    async def load_plugin_by_name(self, name: str) -> Plugin:
        """Import and load a plugin that isn't currently loaded."""
        module = importlib.import_module(f"{self.plugins_dir}.{name}")
        plugin = getattr(module, "plugin", None)
        if not isinstance(plugin, Plugin):
            raise UserInputError(f"{name} is not a plugin")
        await self.load_plugin(plugin)
        return plugin

    async def unload_plugin_by_name(self, name: str) -> None:
        """Unload a loaded plugin by name."""
        plugin = self._plugin_by_name.get(name)
        if plugin is None:
            raise UserInputError(f"plugin {name} is not loaded")
        await self.unload_plugin(plugin)

    def _plugin_module(self, name: str):
        return importlib.import_module(f"{self.plugins_dir}.{name}")

    @property
    def guild(self) -> hikari.GatewayGuild | None:
        """The one guild this bot serves."""
        return self.cache.get_guild(self.config.guild_id)
