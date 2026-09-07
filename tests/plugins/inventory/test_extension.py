"""Inventory extension tests — the grid embed and its ◀/▶ pager menu.

Drives :class:`InventoryPager` (and the :func:`_build_grid` renderer)
directly with fake contexts/menu contexts, mirroring the /experience
TopMenu unit tests: the ◀/▶ buttons page the grid (``PAGE_SIZE`` slots
per page), clamp at both ends, and refuse clicks from anyone but the
slash invoker. The grid embed's shape — title names the member, one
inline field per slot (name ``[ N ]``, value ``<emoji> ×<qty>``),
thumbnail + tip footer — is asserted here at the unit level; the driver
tests cover the full pipeline.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import Enum
from typing import Any, cast

import pytest

from cazzubot.bot import CazzuBot
from cazzubot.items import Item
from cazzubot.tips import TIP_SETS
from plugins.inventory import InventoryPlugin
from plugins.inventory.extension import InventoryPager, _build_grid
from tests.fakes import (
    FakeContext,
    FakeInteraction,
    FakeMenuContext,
    FakeMember,
    menu_button,
)


@pytest.fixture(autouse=True)
def _register_inventory_tips() -> None:
    """Boot would fold the inventory plugin's tip_sets into the registry,
    but these tests render the grid on a plugin-less fixture bot.
    Register the plugin's own sets explicitly (and restore after, since the
    registry is module-global across tests)."""
    from cazzubot.tips import register_tips, unregister_tips

    register_tips("inventory", InventoryPlugin.tip_sets)
    yield
    unregister_tips("inventory")


def _page_items(count: int) -> type[Enum]:
    """``count`` test items (``page:N`` / icon 🐸)."""
    return cast(
        type[Enum],
        Enum(
            "PageItems",
            {
                f"PAGE_{i}": Item(
                    item_id=f"page:{i}",
                    display_name=f"Page Item {i}",
                    icon="🐸",
                    description="",
                )
                for i in range(1, count + 1)
            },
        ),
    )


def _visible(count: int) -> list[tuple[int, str, int]]:
    """A compacted slot list of ``count`` stacks, largest first.

    Mirrors ``_indexed_resolved``'s output for qty-ascending stacks: slot
    1 = the biggest stack (``count``), slot ``count`` = quantity 1.
    """
    return [
        (slot, f"page:{item}", qty)
        for slot, (item, qty) in enumerate(
            ((i, i) for i in range(count, 0, -1)), start=1
        )
    ]


@pytest.fixture
async def registered_bot(bot: CazzuBot) -> AsyncGenerator[CazzuBot, None]:
    """The plain bot with the pager test items registered."""
    bot.items.register("test.pager", _page_items(30))
    yield bot
    bot.items.unregister("test.pager")


async def test_grid_renders_inline_fields_with_user_title(
    registered_bot: CazzuBot, author: FakeMember
) -> None:
    """The grid: title names the user, slots are inline fields with the
    backticked token name and a ``<emoji> ×<qty>`` value."""
    embed = await _build_grid(
        registered_bot,
        [(1, "page:2", 2), (2, "page:1", 1)],
        cast(Any, author),
    )

    assert embed.title == "cirno's Inventory"
    assert embed.author is None
    assert [field.name for field in embed.fields] == [
        "`[ 1 ]`",
        "`[ 2 ]`",
    ]
    assert [field.value for field in embed.fields] == [
        "🐸 ×2",
        "🐸 ×1",
    ]
    # inline layout — Discord wraps 3 per row automatically
    assert all(field.is_inline for field in embed.fields)
    assert (embed.description or "") == ""
    # the thumbnail is the member's pfp and the footer an item tip
    assert embed.thumbnail is not None
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["item"]
    assert embed.footer.icon is None  # unpublished shared cirno emojis


async def test_grid_first_page_is_25_fields(
    registered_bot: CazzuBot, author: FakeMember
) -> None:
    """Page 1 renders the first 25 slots only (the embed caps at 25)."""
    embed = await _build_grid(
        registered_bot, _visible(30), cast(Any, author), page=1
    )

    assert len(embed.fields) == 25
    assert [field.name for field in embed.fields] == [
        f"`[ {n} ]`" for n in range(1, 26)
    ]
    assert embed.fields[0].value == "🐸 ×30"


async def test_grid_empty_state_kept(
    registered_bot: CazzuBot, author: FakeMember
) -> None:
    """An empty inventory keeps the prose empty state, no fields."""
    embed = await _build_grid(registered_bot, [], cast(Any, author))

    assert embed.title == "cirno's Inventory"
    assert embed.description == "Your inventory is empty."
    assert embed.fields == []


def _pager(registered_bot: CazzuBot, ctx: FakeContext) -> InventoryPager:
    """A 30-slot pager (2 pages) on the invoker's own inventory."""
    return InventoryPager(
        registered_bot,
        cast(Any, ctx),
        _visible(30),
        cast(Any, ctx.member),
        page=1,
    )


async def test_pager_next_page_opens_slot_26(
    registered_bot: CazzuBot, ctx: FakeContext
) -> None:
    """▶ from page 1 edits in page 2: the trailing 5 slots."""
    menu = _pager(registered_bot, ctx)
    mctx = FakeMenuContext(FakeInteraction(id=1, member=ctx.member))
    button = menu_button(menu, 1)  # ▶
    await button.callback(mctx)

    embed = mctx.sent[0].embed
    assert embed is not None
    assert [field.name for field in embed.fields] == [
        f"`[ {n} ]`" for n in range(26, 31)
    ]
    assert [field.value for field in embed.fields] == [
        "🐸 ×5",
        "🐸 ×4",
        "🐸 ×3",
        "🐸 ×2",
        "🐸 ×1",
    ]


async def test_pager_prev_page_clamps_at_one(
    registered_bot: CazzuBot, ctx: FakeContext
) -> None:
    """◀ on page 1 stays page 1 (bounds clamped)."""
    menu = _pager(registered_bot, ctx)
    mctx = FakeMenuContext(FakeInteraction(id=1, member=ctx.member))
    button = menu_button(menu, 0)  # ◀
    await button.callback(mctx)

    embed = mctx.sent[0].embed
    assert embed is not None
    assert [field.name for field in embed.fields] == [
        f"`[ {n} ]`" for n in range(1, 26)
    ]


async def test_pager_next_page_clamps_at_last(
    registered_bot: CazzuBot, ctx: FakeContext
) -> None:
    """▶ on the last page stays there (no empty trailing page)."""
    menu = _pager(registered_bot, ctx)
    menu.page = 2
    mctx = FakeMenuContext(FakeInteraction(id=1, member=ctx.member))
    button = menu_button(menu, 1)  # ▶
    await button.callback(mctx)

    embed = mctx.sent[0].embed
    assert embed is not None
    assert [field.name for field in embed.fields] == [
        f"`[ {n} ]`" for n in range(26, 31)
    ]


async def test_pager_denies_foreign_user(
    registered_bot: CazzuBot, ctx: FakeContext
) -> None:
    """A click from anyone but the invoker gets the ephemeral denial."""
    menu = _pager(registered_bot, ctx)
    foreign = FakeMember(id=999, name="other")
    mctx = FakeMenuContext(FakeInteraction(id=1, member=foreign))
    button = menu_button(menu, 1)  # ▶
    await button.callback(mctx)

    assert mctx.sent[0].content == ("This inventory is not yours to page.")
    assert mctx.sent[0].ephemeral is True
