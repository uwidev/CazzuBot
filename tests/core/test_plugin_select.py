"""select_plugins — sandbox allowlist, transitive deps, cycles, ordering."""

from __future__ import annotations

import pytest

from cazzubot.errors import UserInputError
from cazzubot.plugin import Plugin, discover_plugins, select_plugins


def _plugin(name: str, *depends_on: str) -> Plugin:
    """A bare plugin with a name and declared dependencies."""
    plugin = Plugin()
    plugin.name = name
    plugin.depends_on = depends_on
    return plugin


def _names(plugins: list[Plugin]) -> list[str]:
    return [p.name for p in plugins]


# mirrors the real dependency graph; list order simulates discovery order
PLUGINS = [
    _plugin("daily", "experience", "frogs"),
    _plugin("dev"),
    _plugin("experience", "levels", "ranks"),
    _plugin("frogs", "experience"),
    _plugin("levels", "ranks"),
    _plugin("poll"),
    _plugin("quarterly", "frogs"),
    _plugin("ranks", "experience"),
]


def test_none_selects_everything_in_dependency_order() -> None:
    # experience <-> ranks is a cycle, so all three load together as one
    # strongly-connected component (in discovery order)
    assert _names(select_plugins(PLUGINS, None)) == [
        "dev",
        "experience",
        "levels",
        "ranks",
        "frogs",
        "daily",
        "poll",
        "quarterly",
    ]


def test_requested_expands_transitively() -> None:
    assert _names(select_plugins(PLUGINS, ("frogs",))) == [
        "experience",
        "levels",
        "ranks",
        "frogs",
    ]


def test_cycle_loads_together_from_either_side() -> None:
    expected = ["experience", "levels", "ranks"]
    assert _names(select_plugins(PLUGINS, ("experience",))) == expected
    assert _names(select_plugins(PLUGINS, ("ranks",))) == expected
    assert _names(select_plugins(PLUGINS, ("levels",))) == expected


def test_requested_order_and_duplicates_are_irrelevant() -> None:
    assert _names(
        select_plugins(PLUGINS, ("frogs", "experience", "frogs"))
    ) == ["experience", "levels", "ranks", "frogs"]


def test_unknown_plugin_name_raises() -> None:
    with pytest.raises(UserInputError, match="nope"):
        select_plugins(PLUGINS, ("frogs", "nope"))
    with pytest.raises(UserInputError, match="available"):
        select_plugins(PLUGINS, ("nope",))


def test_unknown_declared_dependency_raises() -> None:
    broken = [_plugin("a", "ghost"), _plugin("b")]
    with pytest.raises(UserInputError, match="ghost"):
        select_plugins(broken, None)
    with pytest.raises(UserInputError, match="ghost"):
        select_plugins(broken, ("a",))


def test_real_plugin_set_is_consistent() -> None:
    plugins = discover_plugins("plugins")
    assert {p.name for p in plugins} == {
        "board",
        "channels",
        "counter",
        "daily",
        "dev",
        "experience",
        "frogs",
        "fun",
        "levels",
        "misc",
        "mod",
        "poll",
        "quarterly",
        "ranks",
        "roles",
        "welcome",
    }

    selected = select_plugins(plugins, None)
    assert len(selected) == len(plugins)
    by_name = {p.name: p for p in plugins}
    position = {p.name: i for i, p in enumerate(selected)}

    def reaches(start: str, target: str) -> bool:
        """True when start -> ... -> target along depends_on edges."""
        seen = {start}
        stack = [start]
        while stack:
            for dep in by_name[stack.pop()].depends_on:
                if dep == target:
                    return True
                if dep not in seen:
                    seen.add(dep)
                    stack.append(dep)
        return False

    # a dependency comes before its dependent — unless they form a cycle
    # (strongly-connected components load together)
    for plugin in selected:
        for dep in plugin.depends_on:
            if position[dep] < position[plugin.name]:
                continue
            assert reaches(plugin.name, dep) and reaches(dep, plugin.name)

    # a requested leaf pulls in its whole support network
    assert _names(select_plugins(plugins, ("frogs",))) == [
        "experience",
        "levels",
        "ranks",
        "frogs",
    ]
    assert _names(select_plugins(plugins, ("poll",))) == ["poll"]
