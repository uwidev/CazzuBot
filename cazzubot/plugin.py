"""The plugin system.

A plugin is a self-contained package under ``plugins/`` whose ``__init__.py``
defines exactly one ``Plugin`` subclass instance as ``plugin``::

	from discord.ext import commands
	from cazzubot import Plugin

	class MyFeature(Plugin):
		name = "myfeature"
		cogs = [MyCog]
		schema = ["CREATE TABLE IF NOT EXISTS myfeature (...)"]
		scheduled = {"mytag": my_handler}

	plugin = MyFeature()

The loader discovers it, applies its schema, registers its cogs and its
scheduled-task handlers. That's the whole contract — no central registration.
"""

import importlib
import logging
import pkgutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from discord.ext import commands

if TYPE_CHECKING:
	from cazzubot.bot import CazzuBot

_log = logging.getLogger(__name__)

# A scheduled-task handler: called when a task row with the matching tag is due.
TaskHandler = Callable[["CazzuBot", dict[str, Any]], Awaitable[None]]


class Plugin:
	"""Base class for a feature plugin.

	Subclasses override::

		name       unique plugin id (defaults to the module name)
		cogs       list of discord.py cog classes to register
		schema     list of DDL statements (idempotent)
		scheduled  tag -> handler(bot, payload) for the central scheduler
	"""

	name: str = ""
	cogs: list[type[commands.Cog]] = []
	schema: list[str] = []
	scheduled: dict[str, TaskHandler] = {}

	async def on_load(self, bot: "CazzuBot") -> None:
		"""Hook called after schema + cogs are registered (before ready)."""

	async def on_unload(self, bot: "CazzuBot") -> None:
		"""Hook called when the plugin is unloaded (bot shutdown / hotswap)."""


def discover_plugins(plugins_dir: str) -> list[Plugin]:
	"""Import every ``plugins/*/__init__.py`` and return their ``plugin``.

	Silently skips directories without a ``plugin`` attribute so non-plugin
	packages can coexist.
	"""
	path = Path(plugins_dir)
	plugins: list[Plugin] = []
	if not path.is_dir():
		return plugins

	for module_info in sorted(
		pkgutil.iter_modules([str(path)]), key=lambda m: m.name
	):
		# both packages (plugins/foo/__init__.py) and single modules
		# (plugins/foo.py) are supported
		try:
			module = importlib.import_module(
				f"{path.name}.{module_info.name}"
			)
		except Exception:
			_log.exception("failed to import plugin %s", module_info.name)
			continue

		plugin = getattr(module, "plugin", None)
		if isinstance(plugin, Plugin):
			if not plugin.name:
				plugin.name = module_info.name
			plugins.append(plugin)
			_log.info("discovered plugin: %s", plugin.name)

	return plugins
