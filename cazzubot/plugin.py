"""The plugin system.

A plugin is a self-contained package under ``plugins/`` whose ``__init__.py``
defines exactly one ``Plugin`` subclass instance as ``plugin``::

        from cazzubot import Plugin

        class MyFeature(Plugin):
                name = "myfeature"
                extensions = ["plugins.myfeature.extension"]
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
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from cazzubot.bot import CazzuBot

from cazzubot.errors import UserInputError
from cazzubot.scheduler import TaskPolicy

_log = logging.getLogger(__name__)

# A scheduled-task handler: called when a task row with the matching tag is due.
TaskHandler: TypeAlias = Callable[
    ["CazzuBot", dict[str, Any]], Awaitable[None]
]

# A Plugin.scheduled value: a bare handler, or (handler, policy) for
# per-tag retry/stale configuration (see scheduler.TaskPolicy — max
# attempts, backoff, stale-after). The bare form runs under the defaults.
ScheduledEntry: TypeAlias = TaskHandler | tuple[TaskHandler, TaskPolicy]


class Plugin:
    """Base class for a feature plugin.

    Subclasses override::

            name        unique plugin id (defaults to the module name)
            extensions  import paths of lightbulb extension modules (each
                        defines a module-level ``lightbulb.Loader``)
            schema      list of DDL statements (idempotent)
            scheduled   tag -> handler(bot, payload) for the central
                        scheduler, or tag -> (handler, TaskPolicy) to set
                        the tag's retry/stale configuration
            asset_decl  the plugin's asset declaration enum — each member's
                        value is an ``AssetSpec`` and the member IS the
                        reference; reconciled into the registry at boot
            depends_on  names of plugins this one needs loaded first
                        (transitively expanded by ``select_plugins``; cycles
                        load together as one strongly-connected component)
            enabled     code-level default for whether the plugin loads at
                        boot; the ``plugin.enabled.<name>`` settings key
                        overrides it (see ``filter_enabled``). False = ships
                        disabled — the owner can still enable it at runtime
    """

    name: str = ""
    extensions: list[str] = []
    schema: list[str] = []
    scheduled: dict[str, ScheduledEntry] = {}
    asset_decl: type[Enum] | None = None
    depends_on: tuple[str, ...] = ()
    enabled: bool = True

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


def filter_enabled(
    plugins: list[Plugin], disabled: set[str]
) -> list[Plugin]:
    """Drop disabled plugins and everything that transitively depends on them.

    ``disabled`` names come from settings (runtime overrides) plus any
    plugin whose ``enabled`` class attribute is False (the code default).
    A plugin loads only when it and every declared dependency is enabled —
    a disabled provider would otherwise leave its dependents half-wired
    (imports succeed, scheduler tags and extensions don't). Order is
    preserved; the caller logs what was skipped.
    """
    if not disabled:
        return list(plugins)
    blocked = set(disabled)
    # fixed point: a plugin whose dependency is blocked becomes blocked,
    # which may block further dependents
    changed = True
    while changed:
        changed = False
        for plugin in plugins:
            if plugin.name in blocked:
                continue
            if any(dep in blocked for dep in plugin.depends_on):
                blocked.add(plugin.name)
                changed = True
    return [p for p in plugins if p.name not in blocked]


def select_plugins(
    plugins: list[Plugin], requested: tuple[str, ...] | None
) -> list[Plugin]:
    """Select plugins to load, expanding transitive ``depends_on``.

    ``requested=None`` selects every plugin (production boot). Otherwise
    only the named plugins load, plus every plugin they depend on —
    transitively. Dependencies that form a cycle (e.g. experience <-> ranks)
    are loaded together as one strongly-connected component.

    The result is ordered dependencies-before-dependents (ties broken by
    discovery order) so the loader never sees a plugin before its
    dependencies. Raises ``UserInputError`` for unknown plugin names and
    for declared dependencies that don't exist.
    """
    by_name = {p.name: p for p in plugins}
    discovery = {p.name: i for i, p in enumerate(plugins)}

    # a declared dependency that doesn't exist is a bug, not a runtime
    # surprise — check every plugin in both modes
    for name, plugin in by_name.items():
        for dep in plugin.depends_on:
            if dep not in by_name:
                raise UserInputError(
                    f"plugin {name} declares unknown dependency {dep}"
                )

    if requested is None:
        wanted = list(by_name)
    else:
        unknown = sorted(n for n in requested if n not in by_name)
        if unknown:
            raise UserInputError(
                "unknown plugin(s): "
                + ", ".join(unknown)
                + f" — available: {', '.join(sorted(by_name))}"
            )
        wanted = _with_dependencies(requested, by_name)

    return [
        by_name[name] for name in _topo_order(wanted, by_name, discovery)
    ]


def _with_dependencies(
    requested: tuple[str, ...], by_name: dict[str, Plugin]
) -> list[str]:
    """The requested plugins plus their transitive ``depends_on`` (deduped)."""
    wanted: list[str] = []
    seen: set[str] = set()
    stack = list(requested)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        wanted.append(name)
        stack.extend(by_name[name].depends_on)
    return wanted


def _topo_order(
    names: list[str],
    by_name: dict[str, Plugin],
    discovery: dict[str, int],
) -> list[str]:
    """Dependencies-first order over ``names``; cycles load as one group.

    Strongly-connected components are contracted into single nodes, then a
    Kahn sort runs over the condensation DAG — ties broken by the earliest
    discovery index, members within a component by discovery order.
    """
    edges = {
        name: [dep for dep in by_name[name].depends_on if dep in names]
        for name in names
    }
    components = _scc(names, edges, discovery)

    # condensation: component -> components that depend on it
    comp_of = {
        name: i for i, comp in enumerate(components) for name in comp
    }
    indegree = {i: 0 for i, _ in enumerate(components)}
    dependents: dict[int, set[int]] = {
        i: set() for i, _ in enumerate(components)
    }
    for name in names:
        for dep in edges[name]:
            ci, cd = comp_of[name], comp_of[dep]
            if ci != cd and ci not in dependents[cd]:
                dependents[cd].add(ci)
                indegree[ci] += 1

    rank = {
        i: min(discovery[name] for name in comp)
        for i, comp in enumerate(components)
    }
    ready = sorted(
        (i for i, deg in indegree.items() if deg == 0), key=rank.get
    )
    ordered: list[int] = []
    while ready:
        i = ready.pop(0)
        ordered.append(i)
        for j in dependents[i]:
            indegree[j] -= 1
            if indegree[j] == 0:
                ready.append(j)
                ready.sort(key=rank.get)

    return [name for i in ordered for name in components[i]]


def _scc(
    names: list[str],
    edges: dict[str, list[str]],
    discovery: dict[str, int],
) -> list[list[str]]:
    """Tarjan's strongly-connected components (members in discovery order)."""
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    components: list[list[str]] = []
    counter = 0

    def visit(node: str) -> None:
        """Depth-first visit adding ``node``'s component to ``components``."""
        nonlocal counter
        index[node] = lowlink[node] = counter
        counter += 1
        stack.append(node)
        on_stack.add(node)
        for dep in edges[node]:
            if dep not in index:
                visit(dep)
                lowlink[node] = min(lowlink[node], lowlink[dep])
            elif dep in on_stack:
                lowlink[node] = min(lowlink[node], index[dep])
        if lowlink[node] == index[node]:
            comp: list[str] = []
            while True:
                member = stack.pop()
                on_stack.remove(member)
                comp.append(member)
                if member == node:
                    break
            components.append(sorted(comp, key=discovery.__getitem__))

    for name in names:
        if name not in index:
            visit(name)
    return components
