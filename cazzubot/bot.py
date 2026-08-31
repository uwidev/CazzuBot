"""The bot itself.

``CazzuBot`` owns the shared services (db, settings, scheduler, plugins) and
runs the plugin lifecycle. Plugins reach everything through ``self.bot``.

Depends on: every core service below plus the plugin framework. Depended on
by: ``main.py`` and every plugin (via ``ctx.client.app`` / ``event.app`` /
scheduler-handler args).
"""

import asyncio
import logging
import sys

import hikari
import lightbulb

from cazzubot.assets import AssetError, Assets
from cazzubot.config import Config
from cazzubot.db import Database, SchemaMismatchError
from cazzubot.statuses import Statuses
from cazzubot.errors import UserInputError
from cazzubot.events import EventBus
from cazzubot.inventory import Inventory
from cazzubot.items import Items
from cazzubot.lifecycle import Lifecycle
from cazzubot.plugin import (
    Plugin,
    discover_plugins,
    filter_enabled,
    load_plugin_module,
    select_plugins,
)
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
        """Build the bot and all its shared services from ``config``."""
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
        self.assets = Assets(self, config, plugins_dir)
        self.events = EventBus()
        self.inventory = Inventory(self)
        self.items = Items(self)
        self.statuses = Statuses(self)
        self.lifecycle = Lifecycle(self)

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
        """Connect the db, run schemas, load plugins, start services."""
        _log.info("connecting to database...")
        await self.db.connect()

        # core schema
        await self.db.run_schema(self.settings.schema)
        await self.db.run_schema(self.scheduler.schema)
        await self.db.run_schema(self.assets.schema)
        await self.db.run_schema(self.inventory.schema)
        await self.db.run_schema(self.statuses.schema)

        # discover and load plugins — two phases so any on_load hook can
        # depend on every plugin's schema/extensions being ready (no load
        # order).
        discovered = discover_plugins(self.plugins_dir)
        # plugin enable/disable: the ``plugin.enabled.<name>`` settings key
        # overrides the plugin's code-level ``enabled`` default. Disabled
        # plugins (and their dependents) do not load.
        disabled = {
            p.name for p in discovered if not await self.plugin_enabled(p)
        }
        plugins = filter_enabled(discovered, disabled)
        skipped = [p.name for p in discovered if p not in plugins]
        if skipped:
            _log.warning(
                "skipping plugins: %s",
                ", ".join(
                    f"{name} ({'disabled' if name in disabled else 'depends on disabled plugin'})"
                    for name in skipped
                ),
            )
        if self.config.sandbox_plugins is not None:
            refused = [
                name
                for name in self.config.sandbox_plugins
                if name in {p.name for p in discovered}
                and name not in {p.name for p in plugins}
            ]
            if refused:
                _log.critical(
                    "refusing to boot: requested plugin(s) are disabled: %s "
                    "— enable them first (plugin enable) or drop them from -s",
                    ", ".join(refused),
                )
                raise SystemExit(1)
        try:
            plugins = select_plugins(plugins, self.config.sandbox_plugins)
        except UserInputError as err:
            _log.critical("refusing to boot: %s", err)
            raise SystemExit(1) from err
        if self.config.sandbox:
            _log.warning(
                "sandbox mode: loading %s", [p.name for p in plugins]
            )

        for plugin in plugins:
            await self.load_plugin(plugin, run_hooks=False)

        # boot-time schema guard: every table the DDL defines must exist in
        # the database exactly as defined. Terminate rather than let the
        # on-disk schema silently diverge (extra DB tables are allowed).
        statements = [
            *self.settings.schema,
            *self.scheduler.schema,
            *self.assets.schema,
            *self.inventory.schema,
            *self.statuses.schema,
        ]
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
            try:
                await plugin.on_load(self)
            except AssetError as err:
                # a plugin's boot-time asset drift check failed (e.g. the
                # frogs plugin found a species referencing an undeclared
                # art key) — same fail-fast as the reconcile below
                _log.critical("asset drift — refusing to boot: %s", err)
                raise SystemExit(1) from err

        # central task scheduler
        await self.scheduler.start()

        # asset reconcile at the end of starting (after every on_load hook
        # seeded content rows): register declared files, fail fast on drift
        try:
            await self.assets.reconcile()
        except AssetError as err:
            _log.critical("asset drift — refusing to boot: %s", err)
            raise SystemExit(1) from err

    async def _on_started(self, _event: hikari.StartedEvent) -> None:
        """Log login details; warn if the configured guild is missing."""
        me = self.get_me()
        if me is not None:
            _log.info("logged in as %s (%s)", me, me.id)
        if self.is_alive:
            # the guild dump lands right after StartedEvent; warn only once
            # it has had a moment to arrive (tests boot without a gateway,
            # so is_alive is False there and nothing is scheduled)
            asyncio.create_task(self._warn_if_guild_missing())

    async def _warn_if_guild_missing(self) -> None:
        """Warn (once) if the configured guild never landed in the cache."""
        await asyncio.sleep(2)
        if self.guild is None:
            _log.warning(
                "configured guild %s not found — commands will not work",
                self.config.guild_id,
            )

    async def _on_guild_available(
        self, event: hikari.GuildAvailableEvent
    ) -> None:
        """Log when the configured guild's dump lands in the cache."""
        if event.guild_id == self.config.guild_id:
            _log.info("configured guild %s available", event.guild_id)

    async def _on_stopping(self, _event: hikari.StoppingEvent) -> None:
        """Stop services, unload every plugin, close the database."""
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
        """Apply a plugin's schema, extensions and scheduled handlers.

        Every framework-level effect is **deferred to the lifecycle** at
        the point of application — scheduler rows and handler
        registrations per tag, extension unloading — so unload withdraws
        them structurally (tasks are projections; nothing durable is
        touched).
        """
        await self.db.run_schema(plugin.schema)
        for tag, entry in plugin.scheduled.items():
            # a scheduled entry is a bare handler or (handler, policy)
            handler, policy = (
                entry if isinstance(entry, tuple) else (entry, None)
            )
            self.scheduler.register(tag, handler, policy)
            # undo: drop the tag's task rows (projections, re-armed by the
            # plugin's on_load) and forget the handler callback
            self.lifecycle.defer(
                plugin.name, lambda tag=tag: self.scheduler.drop_tag(tag)
            )
            self.lifecycle.defer(
                plugin.name,
                lambda tag=tag: self._forget_scheduler_handlers(tag),
            )
        if plugin.extensions:
            names = tuple(plugin.extensions)
            await self.lightbulb.load_extensions(*names)
            self.lifecycle.defer(
                plugin.name,
                lambda names=names: self.lightbulb.unload_extensions(
                    *names
                ),
            )
        self.plugins.append(plugin)
        self._plugin_by_name[plugin.name] = plugin
        if plugin.item_decl is not None:
            # items resolve independent of behavior enablement: register the
            # definitions and the consuming flag at load, so a later
            # behavior-disable still leaves holdings visible/consumable
            self.items.register(plugin.name, plugin.item_decl)
            self.items.set_consumable(plugin.name, plugin.items_consumable)
        if run_hooks:
            await plugin.on_load(self)
        _log.info("loaded plugin: %s", plugin.name)

    def _forget_scheduler_handlers(self, tag: str) -> None:
        """Unregister a tag's handler callbacks (the undo of ``register``)."""
        self.scheduler.handlers.pop(tag, None)
        self.scheduler.policies.pop(tag, None)

    async def unload_plugin(self, plugin: Plugin) -> None:
        """Withdraw a plugin's deferred effects and remove it from runtime.

        The lifecycle replays the undos in reverse (extensions, scheduler
        handlers and rows, plus anything the plugin deferred in on_load);
        ``on_unload`` remains for explicit teardown (channels/roles).
        Durable data is never touched — tables and user rows survive.
        """
        failures = await self.lifecycle.withdraw(plugin.name)
        for failure in failures:
            _log.error(
                "undo failed while withdrawing %s",
                plugin.name,
                exc_info=failure,
            )
        await plugin.on_unload(self)
        if plugin.item_decl is not None:
            self.items.unregister(plugin.name)
        self.plugins.remove(plugin)
        self._plugin_by_name.pop(plugin.name, None)
        _log.info("unloaded plugin: %s", plugin.name)

    def affected_by_unload(self, name: str) -> list[str]:
        """Loaded plugin names that must go with ``name``, dependents first.

        The plugin plus every loaded plugin that (transitively) depends on
        it — reloading a provider must also reload its dependents, whose
        imports of the provider's modules would otherwise go stale. Uses
        the bot's load order (dependencies first) to derive the unload
        order (reverse = dependents first); cycles come along naturally
        because their members depend on each other.
        """
        by_name = {p.name: p for p in self.plugins}
        if name not in by_name:
            return []
        dependents: dict[str, set[str]] = {
            p.name: set() for p in self.plugins
        }
        for plugin in self.plugins:
            for dep in plugin.depends_on:
                if dep in by_name:
                    dependents[dep].add(plugin.name)
        affected: set[str] = set()
        stack = [name]
        while stack:
            current = stack.pop()
            if current in affected:
                continue
            affected.add(current)
            stack.extend(dependents.get(current, ()))
        return [
            p.name for p in reversed(self.plugins) if p.name in affected
        ]

    def _purge_modules(self, name: str) -> None:
        """Drop a plugin's module tree so a fresh import picks up changes."""
        prefix = f"{self.plugins_dir}.{name}"
        for mod_name in list(sys.modules):
            if mod_name == prefix or mod_name.startswith(prefix + "."):
                del sys.modules[mod_name]

    async def reload_plugin(self, name: str) -> Plugin:
        """Re-import a plugin and its loaded dependents, in dependency order.

        Unloading a provider while its dependents stay loaded leaves stale
        module references, so the whole affected set (the plugin plus every
        loaded plugin that transitively depends on it) is withdrawn and
        reloaded — dependents first out, dependencies first back in.
        """
        affected = self.affected_by_unload(name)
        if not affected:
            raise UserInputError(f"plugin {name} is not loaded")
        for affected_name in affected:
            await self.unload_plugin(self._plugin_by_name[affected_name])
            self._purge_modules(affected_name)
        reloaded: dict[str, Plugin] = {}
        for affected_name in reversed(affected):
            plugin = load_plugin_module(
                f"{self.plugins_dir}.{affected_name}"
            )
            await self.load_plugin(plugin)
            reloaded[affected_name] = plugin
        return reloaded[name]

    async def load_plugin_by_name(self, name: str) -> Plugin:
        """Import and load a plugin that isn't currently loaded."""
        plugin = load_plugin_module(f"{self.plugins_dir}.{name}")
        await self.load_plugin(plugin)
        return plugin

    async def unload_plugin_by_name(self, name: str) -> None:
        """Unload a plugin (and its loaded dependents) by name."""
        affected = self.affected_by_unload(name)
        if not affected:
            raise UserInputError(f"plugin {name} is not loaded")
        for affected_name in affected:
            await self.unload_plugin(self._plugin_by_name[affected_name])

    # -- plugin enable/disable ----------------------------------------------

    async def plugin_enabled(self, plugin: Plugin) -> bool:
        """Effective enabled state: settings override, else code default.

        The ``plugin.enabled.<name>`` settings key is written by the
        owner's ``plugin enable``/``plugin disable`` commands and survives
        restarts; absent means the plugin's own ``enabled`` class
        attribute decides (e.g. mod ships ``enabled = False``).
        """
        override = await self.settings.get(f"plugin.enabled.{plugin.name}")
        return override if override is not None else plugin.enabled

    async def enable_plugin(self, name: str) -> list[str]:
        """Enable a plugin (persisted) and load it with its dependencies.

        The settings flag is set for the plugin and its whole declared
        dependency chain, then any of them that aren't loaded are loaded
        dependencies-first. Returns the names that were loaded.
        """
        plugins = select_plugins(
            discover_plugins(self.plugins_dir), (name,)
        )
        loaded: list[str] = []
        for plugin in plugins:
            await self.settings.set(f"plugin.enabled.{plugin.name}", True)
            if plugin.name not in self._plugin_by_name:
                await self.load_plugin(plugin)
                loaded.append(plugin.name)
        return loaded

    async def disable_plugin(self, name: str) -> list[str]:
        """Disable a plugin (persisted) and unload it with its dependents.

        The settings flag is set to False (survives restarts), then the
        plugin and every loaded plugin that depends on it are unloaded.
        Returns the unloaded names (empty when it wasn't loaded).
        """
        known = {p.name for p in discover_plugins(self.plugins_dir)}
        if name not in known:
            raise UserInputError(
                f"unknown plugin {name} — available: "
                + ", ".join(sorted(known))
            )
        await self.settings.set(f"plugin.enabled.{name}", False)
        affected = self.affected_by_unload(name)
        if affected:
            for affected_name in affected:
                await self.unload_plugin(
                    self._plugin_by_name[affected_name]
                )
        return affected

    @property
    def guild(self) -> hikari.GatewayGuild | None:
        """The one guild this bot serves."""
        return self.cache.get_guild(self.config.guild_id)
