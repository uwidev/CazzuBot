"""The plugin system.

A plugin is a self-contained package under ``plugins/`` whose ``__init__.py``
defines exactly one ``Plugin`` subclass instance as ``plugin``::

        from cazzubot import Plugin

        class MyFeature(Plugin):
                name = "myfeature"
                extensions = ["plugins.myfeature.cog"]
                schema = ["CREATE TABLE IF NOT EXISTS myfeature (...)"]
                scheduled = {"mytag": my_handler}

        plugin = MyFeature()

The loader discovers it, applies its schema, registers its extensions and its
scheduled-task handlers. That's the whole contract — no central registration.
"""

import importlib
import logging
import pkgutil
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

from cazzubot.errors import UserInputError

_log = logging.getLogger(__name__)

# A scheduled-task handler: called when a task row with the matching tag is due.
TaskHandler = Callable[["CazzuBot", dict[str, Any]], Awaitable[None]]


class Plugin:
    """Base class for a feature plugin.

    Subclasses override::

            name        unique plugin id (defaults to the module name)
            extensions  import paths of lightbulb extension modules (each
                        defines a module-level ``lightbulb.Loader``)
            schema      list of DDL statements (idempotent)
            scheduled   tag -> handler(bot, payload) for the central scheduler
    """

    name: str = ""
    extensions: list[str] = []
    schema: list[str] = []
    scheduled: dict[str, TaskHandler] = {}

    async def on_load(self, _bot: "CazzuBot") -> None:
        """Hook called after schema + extensions are registered (before ready)."""

    async def on_unload(self, _bot: "CazzuBot") -> None:
        """Hook called when the plugin is unloaded (bot shutdown / hotswap)."""


def load_plugin_module(module_name: str) -> Plugin:
    """Import a plugin module and return its ``plugin`` attribute.

    Raises ``UserInputError`` when the module has no usable ``plugin``
    attribute. Defaults ``plugin.name`` to the module's final component
    when the plugin left it empty.
    """
    module = importlib.import_module(module_name)
    plugin = getattr(module, "plugin", None)
    if not isinstance(plugin, Plugin):
        raise UserInputError(f"{module_name} is not a plugin module")
    if not plugin.name:
        plugin.name = module_name.rsplit(".", 1)[-1]
    return plugin


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
