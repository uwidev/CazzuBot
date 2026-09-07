"""get_tip() & the tips registry — plugin registers, core queries.

The strings live in the owning plugins' ``Plugin.tip_sets``; the core
(``cazzubot.tips``) is a registry the plugins fold into at boot via
``register_tips`` and query on render via ``get_tip``. These tests cover
the registry contract (register / query / unregister / collision) and the
two plugin declarations that currently feed it.
"""

from __future__ import annotations

import random
from collections.abc import Generator

import pytest

import cazzubot.tips as tips_mod
from cazzubot.tips import (
    TIP_SETS,
    get_tip,
    register_tips,
    unregister_tips,
)
from plugins.frogs import FrogsPlugin
from plugins.inventory import InventoryPlugin


@pytest.fixture(autouse=True)
def _clean_registry() -> Generator[None, None, None]:
    """Start each test from an empty registry; restore after.

    The registry is module-global, so tests that mutate it must leave it
    clean for the next test. ``_PROVIDER`` is the registry's ownership
    index (mirrors ``cazzubot.items``); clearing it is the teardown of the
    plugin-unload path, which the public API doesn't offer by name.
    """
    tips_mod.TIP_SETS.clear()
    tips_mod._PROVIDER.clear()  # pyright: ignore[reportPrivateUsage]
    yield
    tips_mod.TIP_SETS.clear()
    tips_mod._PROVIDER.clear()  # pyright: ignore[reportPrivateUsage]


def test_get_tip_returns_member_of_requested_context() -> None:
    """Every draw stays inside the requested context's own set."""
    register_tips("probe", {"ctx": ("Alpha", "Beta")})
    for _ in range(50):
        assert get_tip("ctx") in ("Alpha", "Beta")


def test_register_tips_publishes_the_provided_strings() -> None:
    """register_tips makes a context queryable with the plugin's strings."""
    register_tips("probe", {"ctx": ("A", "B", "C")})
    assert set(TIP_SETS["ctx"]) == {"A", "B", "C"}


def test_get_tip_cycles_randomly(monkeypatch: pytest.MonkeyPatch) -> None:
    """The draw is random per call — repeated renders vary (not fixed)."""
    register_tips("probe", {"ctx": ("Alpha", "Beta")})
    monkeypatch.setattr(tips_mod, "random", random.Random(7))
    picks = {get_tip("ctx") for _ in range(50)}
    assert len(picks) > 1


def test_contexts_are_independent() -> None:
    """Different providers' contexts never leak into each other."""
    register_tips("probe-a", {"frog": ("Frog tip",)})
    register_tips("probe-b", {"item": ("Item tip",)})
    assert get_tip("frog") == "Frog tip"
    assert get_tip("item") == "Item tip"
    assert "Item tip" not in TIP_SETS["frog"]


def test_register_same_provider_replaces() -> None:
    """A provider re-registering its own context replaces (hot reload)."""
    register_tips("probe", {"ctx": ("Old",)})
    register_tips("probe", {"ctx": ("New",)})
    assert get_tip("ctx") == "New"


def test_register_foreign_context_raises() -> None:
    """A second provider claiming an owned context is a bug, refused loudly."""
    register_tips("probe-a", {"ctx": ("A's tip",)})
    with pytest.raises(ValueError):
        register_tips("probe-b", {"ctx": ("B's tip",)})


def test_get_tip_unknown_context_raises() -> None:
    with pytest.raises(KeyError):
        get_tip("no-such-context")


def test_unregister_tips_drops_the_provider() -> None:
    """unregister_tips removes every context the provider owned."""
    register_tips("probe", {"ctx": ("Tip",)})
    unregister_tips("probe")
    assert "ctx" not in TIP_SETS
    with pytest.raises(KeyError):
        get_tip("ctx")


# -- plugin declarations (the strings now live with their owners) ----------


def test_frog_plugin_owns_the_frog_tips() -> None:
    """The frog set carries the required tips: check + consume, real shapes."""
    frog = "\n".join(FrogsPlugin.tip_sets["frog"])
    assert "/inventory info <slot>" in frog
    assert "/inventory consume <slot>" in frog
    assert "/inventory thaw <slot>" in frog


def test_inventory_plugin_owns_the_item_tips() -> None:
    """The item set carries check/use/thaw with the real command shapes."""
    item = "\n".join(InventoryPlugin.tip_sets["item"])
    assert "/inventory info <slot>" in item
    assert "/inventory consume <slot> [amount]" in item
    assert "/inventory thaw <slot> [amount]" in item