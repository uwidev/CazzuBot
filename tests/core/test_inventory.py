"""Generic inventory — the shared per-member quantity ledger."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from cazzubot.db import Database
from cazzubot import inventory
from cazzubot.inventory import (
    SCHEMA,
    ItemView,
    add,
    get,
    move_all,
    register_renderer,
    renderer_for,
    rows,
    rows_indexed,
    total,
    unregister_renderer,
)


class _Item:
    """A minimal typed item identity (the InventoryKey protocol)."""

    def __init__(self, key: str) -> None:
        self.key = key


@pytest.fixture
async def inv_db(db: Database) -> Database:
    await db.run_schema(SCHEMA)
    return db


@pytest.fixture(autouse=True)
def _clear_renderers() -> Iterator[None]:
    """The renderer registry is module-global — reset between tests."""
    inventory._RENDERERS.clear()
    yield
    inventory._RENDERERS.clear()


async def test_add_get_and_prune_at_zero(inv_db: Database) -> None:
    item = _Item("frog:leaf_frog:normal")
    await add(inv_db, 1, item, 3)
    assert await get(inv_db, 1, item) == 3

    await add(inv_db, 1, item, -3)  # hits exactly zero → pruned
    assert await get(inv_db, 1, item) == 0
    assert await inv_db.fetchval("SELECT COUNT(*) FROM inventory") == 0

    await add(inv_db, 1, item, 2)
    await add(inv_db, 1, item, -5)  # goes negative → pruned, not negative
    assert await get(inv_db, 1, item) == 0


async def test_rows_and_total_respect_prefix(inv_db: Database) -> None:
    await add(inv_db, 1, _Item("frog:leaf_frog:normal"), 3)
    await add(inv_db, 1, _Item("frog:classy_frog:frozen"), 1)
    await add(inv_db, 1, _Item("badge:first_capture"), 1)

    assert await total(inv_db, 1) == 5  # everything
    assert await total(inv_db, 1, prefix="frog:") == 4
    assert await rows(inv_db, 1, prefix="frog:") == [
        ("frog:classy_frog:frozen", 1),
        ("frog:leaf_frog:normal", 3),
    ]
    assert await rows(inv_db, 1, prefix="badge:") == [
        ("badge:first_capture", 1)
    ]


async def test_move_all_folds_stacks_across_members(
    inv_db: Database,
) -> None:
    normal = _Item("frog:leaf_frog:normal")
    frozen = _Item("frog:leaf_frog:frozen")
    await add(inv_db, 1, normal, 3)
    await add(inv_db, 1, frozen, 2)
    await add(inv_db, 2, normal, 1)

    await move_all(inv_db, normal, frozen)

    assert await get(inv_db, 1, frozen) == 5  # 2 + 3 folded
    assert await get(inv_db, 1, normal) == 0  # src dropped
    assert await get(inv_db, 2, frozen) == 1
    assert await get(inv_db, 2, normal) == 0


async def test_move_all_is_idempotent(inv_db: Database) -> None:
    normal = _Item("frog:leaf_frog:normal")
    frozen = _Item("frog:leaf_frog:frozen")
    await add(inv_db, 1, normal, 3)

    await move_all(inv_db, normal, frozen)
    await move_all(inv_db, normal, frozen)  # no src rows left → no-op

    assert await get(inv_db, 1, frozen) == 3
    assert await get(inv_db, 1, normal) == 0


# -- renderer registry (how namespaces present themselves) ------------------


def _leaf(item_key: str, qty: int) -> ItemView:
    return ItemView(icon="🐸", label=f"{item_key} x{qty}")


def test_renderer_for_unregistered_namespace_uses_default() -> None:
    """An unknown prefix renders the raw key — degrades, doesn't crash."""
    view = renderer_for("unknown")("frog:leaf_frog:normal", 3)
    assert view == ItemView(icon="", label="frog:leaf_frog:normal")


def test_register_and_render_by_prefix() -> None:
    register_renderer("frog", _leaf)
    assert renderer_for("frog")("frog:leaf_frog:normal", 4) == _leaf(
        "frog:leaf_frog:normal", 4
    )
    # other namespaces untouched (default)
    assert renderer_for("badge")("badge:x", 1) == ItemView(
        icon="", label="badge:x"
    )


def test_register_replaces_and_unregister_falls_back() -> None:
    register_renderer("frog", _leaf)
    register_renderer("frog", lambda k, q: ItemView(icon="x", label=k))
    assert renderer_for("frog")("a", 1) == ItemView(icon="x", label="a")

    unregister_renderer("frog")
    assert renderer_for("frog")("a", 1) == ItemView(icon="", label="a")


def test_renderers_are_isolated_by_prefix() -> None:
    """Two namespaces render independently through the shared registry."""
    register_renderer("frog", lambda k, q: ItemView(icon="🐸", label=k))
    register_renderer("badge", lambda k, q: ItemView(icon="🏅", label=k))
    assert renderer_for("frog")("frog:leaf_frog:normal", 1) == ItemView(
        icon="🐸", label="frog:leaf_frog:normal"
    )
    assert renderer_for("badge")("badge:first_capture", 1) == ItemView(
        icon="🏅", label="badge:first_capture"
    )


# -- derived indices (grid slots address items deterministically) -----------


async def test_rows_indexed_assigns_deterministic_slots(
    inv_db: Database,
) -> None:
    await add(inv_db, 1, _Item("frog:leaf_frog:normal"), 3)
    await add(inv_db, 1, _Item("frog:classy_frog:frozen"), 1)
    await add(inv_db, 1, _Item("badge:first_capture"), 1)

    assert await rows_indexed(inv_db, 1) == [
        (1, "badge:first_capture", 1),
        (2, "frog:classy_frog:frozen", 1),
        (3, "frog:leaf_frog:normal", 3),
    ]
    # stable across calls (same ORDER BY item) — slots survive re-render
    assert await rows_indexed(inv_db, 1) == await rows_indexed(inv_db, 1)


async def test_rows_indexed_respects_prefix_and_renumbering(
    inv_db: Database,
) -> None:
    await add(inv_db, 1, _Item("frog:leaf_frog:normal"), 3)
    await add(inv_db, 1, _Item("frog:classy_frog:frozen"), 1)
    await add(inv_db, 1, _Item("badge:first_capture"), 1)

    assert await rows_indexed(inv_db, 1, prefix="frog:") == [
        (1, "frog:classy_frog:frozen", 1),
        (2, "frog:leaf_frog:normal", 3),
    ]
