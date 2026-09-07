"""Generic /inventory through the offline driver.

The commands read the shared ledger and render embeds: ``view`` as a paged
inline-field grid (one inline embed field per slot — the name a backticked
``[ N ]`` token, the value the item's display name with ``×<qty>`` —
Discord wraps 3 per row; 25 slots per page, page navigation rendered
only when 26+ unique items exceed one page, and the title names the
member), ``info`` as a description card (thumbnail
from the item's asset, title the name, the description prose, then one
field per item ``field``). These tests seed real inventory rows, run the
commands end-to-end via ``run_slash``/``press_button``, and assert the
rendered embeds.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from enum import Enum
from typing import cast

import hikari
import pendulum
import pytest

from core.bot import CazzuBot
from core.models import FrogState, FrogItemKey
from core.tips import TIP_SETS
from tests.driver import (
    attached_buttons,
    press_button,
    run_slash,
    wait_for_menu,
)
from tests.fakes import rest_of

# a grid slot field's name is the backticked bracket token ``[ N ]``;
# used to verify slots stay contiguous across the rendered fields
_SLOT_NAME_RE = re.compile(r"^`\[ (\d+) \]`$")


def _rendered_slots(fields: Sequence[hikari.EmbedField]) -> list[str]:
    """The slot numbers the grid rendered as field names, in order."""
    slots: list[str] = []
    for field in fields:
        match = _SLOT_NAME_RE.match(field.name or "")
        if match is not None:
            slots.append(match.group(1))
    return slots


async def _view_embed(bot: CazzuBot, *, user_id: int) -> hikari.Embed:
    """Run ``inventory view`` and return the initial grid embed.

    The paged view blocks on its pager's 30s attach window, so the driver's
    3s response budget can't outlast it — the command runs as a background
    task that gets cancelled once the initial response lands (the response
    is minted before any pager attach begins), and the embed is read back
    from the fake REST log. Single-page inventories attach no pager and
    the task finishes on its own; the cancel is then a harmless no-op.
    """
    rest = rest_of(bot)
    snapshot = len(rest.interaction_log["responses"])
    task = asyncio.create_task(
        run_slash(bot, "inventory view", user_id=user_id, timeout=10.0)
    )
    try:
        for _ in range(500):  # up to ~5s for the initial response
            if len(rest.interaction_log["responses"]) > snapshot:
                break
            await asyncio.sleep(0.01)
        else:
            raise TimeoutError("inventory view never produced a response")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    new = [
        (rtype, payload)
        for _token, rtype, payload in rest.interaction_log["responses"][
            snapshot:
        ]
    ]
    assert new, "no inventory view response recorded"
    rtype, payload = new[0]
    assert rtype == hikari.ResponseType.MESSAGE_CREATE
    embed = payload.get("embed")
    assert embed is not None
    return embed


async def _seed_frogs(bot: CazzuBot, uid: int) -> None:
    from plugins.frogs.db import FrogItem

    await bot.inventory.add(
        uid, FrogItem(FrogItemKey.BASIC, FrogState.NORMAL), 3
    )
    await bot.inventory.add(
        uid, FrogItem(FrogItemKey.BASIC, FrogState.FROZEN), 1
    )


async def test_inventory_view_renders_inline_field_grid(
    full_bot: CazzuBot,
) -> None:
    """Seeded frogs render as an inline-field grid titled with the name."""
    await _seed_frogs(full_bot, 424242)

    embed = await _view_embed(full_bot, user_id=424242)

    # inline-field grid: one field per visible stack (qty descending —
    # normal ×3 leads, frozen ×1 follows), name the backticked slot token,
    # value the item emoji with ×qty — no prose description
    assert [field.name for field in embed.fields] == [
        "`[ 1 ]`",
        "`[ 2 ]`",
    ]
    assert [field.value for field in embed.fields] == [
        "🐸 ×3",
        "🧊 ×1",
    ]
    # inline layout — Discord wraps 3 per row automatically
    assert all(field.is_inline for field in embed.fields)
    assert (embed.description or "") == ""
    # no author field — the title names the member instead, with the real
    # display name (the driver's off-the-wire member is "tester")
    assert embed.author is None
    assert embed.title == "tester's Inventory"
    assert embed.thumbnail is not None
    assert embed.thumbnail.url == (
        "https://cdn.discordapp.com/embed/avatars/"
        f"{(424242 >> 22) % 6}.png"
    )
    # the footer cycles one random item tip (how to check/use/thaw a slot)
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["item"]
    # no footer icon while the shared cirno emojis are unpublished
    assert embed.footer.icon is None


async def _seed_dev_like_inventory(bot: CazzuBot, uid: int) -> None:
    """Five stacks mirroring the reported dev DB: four resolved frogs plus
    one ``frog:classy_frog:*`` stack left over from the pre-rename species
    key (retired — no longer resolves in the item registry)."""
    for item, qty in (
        ("frog:basic:normal", 40),
        ("frog:classy:normal", 1),
        (
            "frog:classy_frog:normal",
            4,
        ),  # stale: sorts between classy/froggers
        ("frog:froggers:normal", 1),
        ("frog:pog:normal", 2),
    ):
        await bot.inventory.add(uid, item, qty)


async def test_inventory_view_compacts_stale_slot_away(
    full_bot: CazzuBot,
) -> None:
    """A stale stack is hidden AND compacted: slots read 1..n, never gapped.

    Reproduces the reported bug: ``frog:classy_frog:normal`` sorted between
    classy and froggers and rendered the grid as slots 1, 2, 4, 5.
    """
    await _seed_dev_like_inventory(full_bot, 424242)

    embed = await _view_embed(full_bot, user_id=424242)

    # grid framework: one inline field per visible stack; the hidden stack
    # never renders a slot number — no gap between 2 and 3
    assert _rendered_slots(embed.fields) == ["1", "2", "3", "4"]
    # qty descending: the biggest stack (basic 40) leads the grid, then
    # pog 2 — the qty-1 stacks (classy/froggers, item order) close it out
    assert [field.value for field in embed.fields] == [
        "🐸 ×40",
        "🐸 ×2",
        "🐸 ×1",
        "🐸 ×1",
    ]


async def test_inventory_info_cannot_reach_hidden_stack(
    full_bot: CazzuBot,
) -> None:
    """Slots compact for info too: the stale stack's would-be slot is gone."""
    await _seed_dev_like_inventory(full_bot, 424242)

    # 4 visible slots by qty desc: 1=basic(40), 2=pog(2), 3=classy(1),
    # 4=froggers(1) — the Pog Frog sits at 2 (it was at 4 under item
    # order / slot 5 before compaction) ...
    embed = await _info_embed(full_bot, 424242, 2)
    assert embed.title == "Pog Frog"

    # ... and a slot past the compacted end is out of bounds (previously
    # slot 5 addressed the hidden stack's neighbourhood)
    result = await run_slash(
        full_bot, "inventory info", options={"slot": 5}, user_id=424242
    )
    assert result.exceptions == []
    first_response = result.first_response
    assert first_response is not None
    assert "No item in slot **5**." in str(
        first_response.get("content", "")
    )


async def test_inventory_grid_uses_published_asset_emoji(
    full_bot: CazzuBot,
) -> None:
    """Published EMOJI-kind icon_assets replace the static item emoji.

    Each frog state has its own emoji asset; when published, the grid
    value shows the custom ``<:name:id>`` emoji instead of the static
    ``🐸`` icon.
    """
    from core.assets import asset_key
    from plugins.frogs.assets import FrogAsset

    await _seed_frogs(full_bot, 424242)
    # simulate published assets (offline tests seed rows with NULL url —
    # the "not published yet" state that exercises the fallback instead);
    # each frog state has its own emoji asset
    await full_bot.db.executemany(
        "UPDATE asset SET url = ? WHERE key = ?",
        [
            (
                "<:frog_basic:123456789012345678>",
                asset_key(FrogAsset.FROG_BASIC),
            ),
            (
                "<:frog_frozen:123456789012345678>",
                asset_key(FrogAsset.FROG_BASIC_FROZEN),
            ),
        ],
    )

    embed = await _view_embed(full_bot, user_id=424242)

    # qty desc: the ×3 normal stack leads, the ×1 frozen stack follows —
    # both as the published custom emoji, not the static 🐸
    assert [field.value for field in embed.fields] == [
        "<:frog_basic:123456789012345678> ×3",
        "<:frog_frozen:123456789012345678> ×1",
    ]


async def test_inventory_view_sorts_frozen_items_last(
    full_bot: CazzuBot,
) -> None:
    """Frozen-frog trophies sort after every live item, even when largest.

    The frozen-last rule wins over quantity: a frozen stack of 50 still
    trails a live stack of 1. Live items keep quantity-descending order.
    """
    await full_bot.inventory.add(424242, "frog:basic:normal", 1)
    await full_bot.inventory.add(424242, "frog:basic:frozen", 50)
    await full_bot.inventory.add(424242, "remains", 2)

    embed = await _view_embed(full_bot, user_id=424242)

    assert [field.name for field in embed.fields] == [
        "`[ 1 ]`",
        "`[ 2 ]`",
        "`[ 3 ]`",
    ]
    # live items first (qty desc: remains 2, then basic 1), frozen last
    assert [field.value for field in embed.fields] == [
        "💀 ×2",
        "🐸 ×1",
        "🧊 ×50",
    ]


async def test_inventory_empty_state(full_bot: CazzuBot) -> None:
    """A member with no holdings sees the empty state, not an error."""
    embed = await _view_embed(full_bot, user_id=424242)

    assert embed.description == "Your inventory is empty."
    assert embed.fields == []


# -- the ◀/▶ pager ---------------------------------------------------------


async def test_inventory_view_single_page_has_no_pager(
    full_bot: CazzuBot,
) -> None:
    """25 or fewer unique items fit one page — no ◀/▶ navigation renders.

    The pager attaches only when the grid actually pages (26+ unique
    items); a single page responds with the bare grid embed (no component
    rows) and attaches nothing, so the response never blocks on a pager
    attach window.
    """
    provider = await _register_page_items(full_bot, 25)
    try:
        for i in range(1, 26):
            await full_bot.inventory.add(424242, f"page:{i}", i)
        result = await run_slash(
            full_bot, "inventory view", user_id=424242, timeout=10.0
        )
    finally:
        full_bot.items.unregister(provider)
    assert result.exceptions == []
    assert result.response_type == hikari.ResponseType.MESSAGE_CREATE
    first = result.first_response
    assert first is not None
    # the grid embed renders but no component rows ride along (lightbulb
    # serializes the omitted kwarg as UNDEFINED), and no menu was attached
    # for the 30s window
    nav = first.get("components")
    assert nav in (None, hikari.UNDEFINED) or nav == []
    assert attached_buttons(full_bot) == {}


async def test_inventory_view_pager_appears_at_26_slots(
    full_bot: CazzuBot,
) -> None:
    """26 unique items overflow one page, so the ◀/▶ navigation appears."""
    provider = await _register_page_items(full_bot, 26)
    try:
        for i in range(1, 27):
            await full_bot.inventory.add(424242, f"page:{i}", i)
        task = asyncio.create_task(
            run_slash(
                full_bot, "inventory view", user_id=424242, timeout=10.0
            )
        )
        buttons = await wait_for_menu(full_bot)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    finally:
        full_bot.items.unregister(provider)
    assert set(buttons) == {"◀", "▶"}


async def _register_page_items(bot: CazzuBot, count: int) -> str:
    """Register ``count`` test items (provider name ``test.pager``).

    The games' real item sets are small (the frog species), so the paging
    tests register their own unique items to exceed the 25-field embed
    cap. Returns the provider name for a finally-guarded unregister.
    """
    from core.items import Item

    items = cast(
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
    provider = f"test.pager.{count}"
    bot.items.register(provider, items)
    return provider


async def _press_page(
    bot: CazzuBot, buttons: dict[str, str], emoji: str
) -> hikari.Embed:
    """Press ``emoji`` as the invoker and return the edited grid embed."""
    press = await press_button(
        bot, custom_id=buttons[emoji], message_id=555, user_id=424242
    )
    assert press.exceptions == []
    # respond(edit=True) is the atomic ack+edit — no "thinking" bubble
    assert press.response_type == hikari.ResponseType.MESSAGE_UPDATE
    first_response = press.first_response
    assert first_response is not None
    embed = first_response.get("embed")
    assert embed is not None
    return embed


async def test_inventory_view_pages_over_25_slots(
    full_bot: CazzuBot,
) -> None:
    """26+ stacks page at 25 fields: ◀/▶ move between pages and clamp.

    The embed caps at 25 fields, so slot 26 starts page 2 (only 26+ get a
    pager — single-page inventories render no navigation). The pager
    mirrors /experience leaderboard's TopMenu: page from the invoker
    only, clamp at both ends.
    """
    provider = await _register_page_items(full_bot, 30)
    try:
        for i in range(1, 31):
            await full_bot.inventory.add(424242, f"page:{i}", i)
        # 30 stacks, qty descending: slot 1 = page:30 (×30) … slot 30 =
        # page:1 (×1) → page 1 holds slots 1-25, page 2 holds slots 26-30
        task = asyncio.create_task(
            run_slash(
                full_bot, "inventory view", user_id=424242, timeout=10.0
            )
        )
        buttons = await wait_for_menu(full_bot)
        try:
            # page 1: 25 fields, slots 1-25 — and ◀ clamps here
            page1 = await _press_page(full_bot, buttons, "◀")
            assert _rendered_slots(page1.fields) == [
                str(n) for n in range(1, 26)
            ]
            assert page1.fields[0].value == "🐸 ×30"

            # ▶ opens page 2: the trailing 5 slots
            page2 = await _press_page(full_bot, buttons, "▶")
            assert _rendered_slots(page2.fields) == [
                str(n) for n in range(26, 31)
            ]
            assert [field.value for field in page2.fields] == [
                "🐸 ×5",
                "🐸 ×4",
                "🐸 ×3",
                "🐸 ×2",
                "🐸 ×1",
            ]

            # ▶ again clamps at page 2 (no empty page 3)
            clamped = await _press_page(full_bot, buttons, "▶")
            assert _rendered_slots(clamped.fields) == [
                str(n) for n in range(26, 31)
            ]

            # ◀ returns to page 1
            back = await _press_page(full_bot, buttons, "◀")
            assert _rendered_slots(back.fields) == [
                str(n) for n in range(1, 26)
            ]
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    finally:
        full_bot.items.unregister(provider)


async def test_inventory_view_pager_refuses_foreign_user(
    full_bot: CazzuBot,
) -> None:
    """A non-invoker click gets the ephemeral "not yours to page" denial."""
    provider = await _register_page_items(full_bot, 30)
    try:
        for i in range(1, 31):
            await full_bot.inventory.add(424242, f"page:{i}", i)
    except BaseException:
        full_bot.items.unregister(provider)
        raise

    task = asyncio.create_task(
        run_slash(full_bot, "inventory view", user_id=424242, timeout=10.0)
    )
    buttons = await wait_for_menu(full_bot)
    try:
        press = await press_button(
            full_bot, custom_id=buttons["▶"], message_id=555, user_id=7
        )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        full_bot.items.unregister(provider)

    assert press.exceptions == []
    assert press.response_type == hikari.ResponseType.MESSAGE_CREATE
    assert press.first_response is not None
    assert (
        press.first_response.get("flags", 0) & hikari.MessageFlag.EPHEMERAL
    )
    assert "This inventory is not yours to page." in str(
        press.first_response.get("content", "")
    )


# -- /inventory info ---------------------------------------------------------


async def _info_embed(bot: CazzuBot, uid: int, slot: int) -> hikari.Embed:
    """Run ``/inventory info <slot>`` as ``uid`` and return the embed."""
    result = await run_slash(
        bot, "inventory info", options={"slot": slot}, user_id=uid
    )
    assert result.exceptions == []
    assert result.response_type == hikari.ResponseType.MESSAGE_CREATE
    first_response = result.first_response
    assert first_response is not None
    embed = first_response.get("embed")
    assert embed is not None
    return embed


async def test_inventory_info_shows_item_card(full_bot: CazzuBot) -> None:
    """info renders the card: asset thumbnail, name, description, fields."""
    from core.assets import asset_key
    from plugins.frogs.assets import FrogAsset

    await _seed_frogs(full_bot, 424242)
    # publish the frozen frog's emoji asset (slot 2 = frozen now: the ×3
    # normal stack leads slot 1 under qty desc)
    await full_bot.db.executemany(
        "UPDATE asset SET url = ? WHERE key = ?",
        [
            (
                "<:frog_frozen:123456789012345678>",
                asset_key(FrogAsset.FROG_BASIC_FROZEN),
            ),
            (
                "<:frog_basic:987654321098765432>",
                asset_key(FrogAsset.FROG_BASIC),
            ),
        ],
    )

    embed = await _info_embed(full_bot, 424242, 2)

    assert embed.title == "Basic Frog (Frozen)"
    assert "frozen solid" in (embed.description or "")
    assert (
        embed.thumbnail is not None
        and embed.thumbnail.url
        == "https://cdn.discordapp.com/emojis/123456789012345678.png"
    )
    # a frozen frog is a trophy: the info card describes the thaw gamble,
    # not consumption
    assert [field.name for field in embed.fields] == ["On thaw"]
    assert [field.value for field in embed.fields] == [
        "Frozen and non-consumable. Thawing this frog has a 50% chance "
        "to restore it, and 50% to leave Frog Remains (3 exp)."
    ]
    # the footer cycles one random item tip (the /inventory view set)
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["item"]
    # no footer icon while the shared cirno emojis are unpublished
    assert embed.footer.icon is None


async def test_inventory_info_unpublished_asset_has_no_thumbnail(
    full_bot: CazzuBot,
) -> None:
    """An unpublished icon asset renders the card without a thumbnail."""
    await _seed_frogs(full_bot, 424242)

    embed = await _info_embed(full_bot, 424242, 2)

    assert embed.title == "Basic Frog (Frozen)"
    assert embed.thumbnail is None
    assert [field.name for field in embed.fields] == ["On thaw"]
    # the tip footer renders regardless of the asset's publish state
    assert embed.footer is not None
    assert embed.footer.text in TIP_SETS["item"]


async def test_inventory_info_unknown_slot_is_an_error(
    full_bot: CazzuBot,
) -> None:
    """Info is possession-driven: an empty slot is rejected, like consume."""
    await _seed_frogs(full_bot, 424242)

    result = await run_slash(
        full_bot, "inventory info", options={"slot": 5}, user_id=424242
    )

    assert result.exceptions == []
    first_response = result.first_response
    assert first_response is not None
    assert first_response.get("flags", 0) & hikari.MessageFlag.EPHEMERAL
    assert "No item in slot **5**." in str(
        first_response.get("content", "")
    )


# -- /inventory thaw ---------------------------------------------------------


async def test_inventory_consume_refuses_frozen_frogs(
    full_bot: CazzuBot,
) -> None:
    """Frozen frogs are trophies — consume refuses before any confirm."""
    await full_bot.inventory.add(424242, "frog:basic:frozen", 2)

    result = await run_slash(
        full_bot, "inventory consume", options={"slot": 1}, user_id=424242
    )

    assert result.exceptions == []
    first_response = result.first_response
    assert first_response is not None
    assert first_response.get("flags", 0) & hikari.MessageFlag.EPHEMERAL
    assert "Frozen frogs cannot be consumed" in str(
        first_response.get("content", "")
    )
    # nothing was consumed
    assert await full_bot.inventory.get(424242, "frog:basic:frozen") == 2


async def test_inventory_thaw_confirms_and_rolls(
    full_bot: CazzuBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """thaw confirms first, then rolls each unit (deterministic 1:1 here)."""
    from plugins.frogs import thaw as thaw_mod

    await full_bot.inventory.add(424242, "frog:pog:frozen", 3)
    seq = iter([0.1, 0.9])

    class _Fixed:
        def random(self) -> float:
            return next(seq)

    monkeypatch.setattr(thaw_mod.random, "random", _Fixed().random)

    task = asyncio.create_task(
        run_slash(
            full_bot,
            "inventory thaw",
            options={"slot": 1, "amount": 2},
            user_id=424242,
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    press = await press_button(
        full_bot,
        custom_id=buttons["Yes"],
        message_id=555,
        user_id=424242,
    )
    result = await task

    assert press.exceptions == []
    assert result.exceptions == []
    # 2 thawed: one survived as normal Pog, one became Frog Remains
    assert await full_bot.inventory.get(424242, "frog:pog:frozen") == 1
    assert await full_bot.inventory.get(424242, "frog:pog:normal") == 1
    assert await full_bot.inventory.get(424242, "remains") == 1
    # the post-thaw tally edits the prompt message
    assert any("embed" in payload for _mid, payload in result.edits)


def _footer_icon(embed: hikari.Embed) -> str:
    """The embed's footer icon URL ('' when absent)."""
    if embed.footer is None or embed.footer.icon is None:
        return ""
    return str(embed.footer.icon.url)


async def test_inventory_consume_embeds_use_bot_avatar_footer(
    full_bot: CazzuBot,
) -> None:
    """Both consume embeds (confirmation + final) stamp the bot avatar
    as the footer icon, not the -sarono catbox icon."""
    from core.utils import BOT_AVATAR_URL

    await full_bot.inventory.add(424242, "frog:basic:normal", 2)

    task = asyncio.create_task(
        run_slash(
            full_bot,
            "inventory consume",
            options={"slot": 1},
            user_id=424242,
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    press = await press_button(
        full_bot,
        custom_id=buttons["Yes"],
        message_id=555,
        user_id=424242,
    )
    result = await task
    assert press.exceptions == []
    assert result.exceptions == []

    # confirmation embed: the initial slash response
    first_response = result.first_response
    assert first_response is not None
    confirm_embed = first_response.get("embed")
    assert confirm_embed is not None
    assert confirm_embed.title == "**Confirmation**"
    assert _footer_icon(confirm_embed) == BOT_AVATAR_URL
    assert "catbox" not in _footer_icon(confirm_embed)

    # final embed: edited into the prompt message
    final_payloads = [
        payload
        for _mid, payload in result.edits
        if isinstance(payload.get("embed"), hikari.Embed)
    ]
    assert final_payloads
    final_embed = final_payloads[0]["embed"]
    assert (
        final_embed.title is not None and "Consumed" in final_embed.title
    )
    assert _footer_icon(final_embed) == BOT_AVATAR_URL
    assert "catbox" not in _footer_icon(final_embed)


async def _consume_confirmation_and_final_embeds(
    full_bot: CazzuBot,
) -> tuple[hikari.Embed, hikari.Embed]:
    """Run a yes-confirmed consume of slot 1 and return ``(confirm, final)``."""
    task = asyncio.create_task(
        run_slash(
            full_bot,
            "inventory consume",
            options={"slot": 1},
            user_id=424242,
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    press = await press_button(
        full_bot,
        custom_id=buttons["Yes"],
        message_id=555,
        user_id=424242,
    )
    result = await task
    assert press.exceptions == []
    assert result.exceptions == []

    first_response = result.first_response
    assert first_response is not None
    confirm_embed = first_response.get("embed")
    assert confirm_embed is not None
    assert confirm_embed.title == "**Confirmation**"

    final_payloads = [
        payload
        for _mid, payload in result.edits
        if isinstance(payload.get("embed"), hikari.Embed)
    ]
    assert final_payloads
    final_embed = final_payloads[0]["embed"]
    assert (
        final_embed.title is not None and "Consumed" in final_embed.title
    )
    return confirm_embed, final_embed


async def test_inventory_consume_embeds_use_item_thumbnail_when_published(
    full_bot: CazzuBot,
) -> None:
    """When the art asset is published, both consume embeds (confirmation +
    final) set the thumbnail to the item's CDN image URL."""
    from core.assets import asset_key
    from plugins.frogs.assets import FrogAsset

    await full_bot.inventory.add(424242, "frog:basic:normal", 2)
    # publish the basic frog's emoji asset
    await full_bot.db.executemany(
        "UPDATE asset SET url = ? WHERE key = ?",
        [
            (
                "<:frog_basic:123456789012345678>",
                asset_key(FrogAsset.FROG_BASIC),
            ),
        ],
    )

    (
        confirm_embed,
        final_embed,
    ) = await _consume_confirmation_and_final_embeds(full_bot)

    thumbnail_url = (
        "https://cdn.discordapp.com/emojis/123456789012345678.png"
    )
    assert (
        confirm_embed.thumbnail is not None
        and confirm_embed.thumbnail.url == thumbnail_url
    )
    assert (
        final_embed.thumbnail is not None
        and final_embed.thumbnail.url == thumbnail_url
    )


async def test_inventory_consume_embeds_have_no_thumbnail_when_unpublished(
    full_bot: CazzuBot,
) -> None:
    """An unpublished art asset (NULL url) leaves both consume embeds
    without a thumbnail — no "None" leaks."""
    await full_bot.inventory.add(424242, "frog:basic:normal", 2)

    (
        confirm_embed,
        final_embed,
    ) = await _consume_confirmation_and_final_embeds(full_bot)

    assert confirm_embed.thumbnail is None
    assert final_embed.thumbnail is None


async def test_inventory_consume_final_embed_shows_effects_and_result(
    full_bot: CazzuBot,
) -> None:
    """The "Consumed!" embed shows the item's effects (description prose +
    the "On consumption" field), the seasonal exp before/after (exp items
    only), the resulting status when one was granted, and the
    stack-consumption result."""
    await full_bot.inventory.add(424242, "frog:pog:normal", 2)

    (
        _confirm_embed,
        final_embed,
    ) = await _consume_confirmation_and_final_embeds(full_bot)

    # the item's effect prose: the description and the "On consumption" blurb
    assert (final_embed.description or "") == "A frog with a pog."
    assert [field.name for field in final_embed.fields] == [
        "On consumption",
        "Seasonal Exp",
        "Status",
        "Resulting Pog Frog",
    ]
    consumption = next(
        field
        for field in final_embed.fields
        if field.name == "On consumption"
    )
    assert "Grants **30** seasonal exp." in consumption.value
    # the exp outcome (fresh member: 0 before, 30 after one pog) sits before
    # the status and the stack-consumption result —
    exp_field = next(
        field
        for field in final_embed.fields
        if field.name == "Seasonal Exp"
    )
    assert exp_field.value == "**`0`** -> **`30`**"
    # the resulting status (the pog reaction status, read back from the live
    # contribution) — the describe() prose, not just the prospective blurb
    status_field = next(
        field for field in final_embed.fields if field.name == "Status"
    )
    assert status_field.value == (
        "For 1 hour, a **1%** chance the bot reacts to your messages "
        "with the froggers emoji (10s cooldown)."
    )
    # the stack-consumption result (what consuming them did): the qty line
    result_field = next(
        field
        for field in final_embed.fields
        if field.name == "Resulting Pog Frog"
    )
    assert result_field.value == "**`2`** -> **`1`**"


async def test_inventory_consume_confirmation_previews_effects_exp_and_status(
    full_bot: CazzuBot,
) -> None:
    """The confirmation step previews the consume outcome before Yes.

    The pre-consume embed shows the same sections the final "Consumed!"
    embed reports, phrased as a projection: the item's effect fields (the
    "On consumption" blurb), the seasonal exp before/after (predicted from
    the item module's exp oracle), and the resulting status when the item
    grants one — so the member sees what consuming will do up front.
    """
    await full_bot.inventory.add(424242, "frog:pog:normal", 2)

    (
        confirm_embed,
        _final_embed,
    ) = await _consume_confirmation_and_final_embeds(full_bot)

    assert confirm_embed.title == "**Confirmation**"
    # the item's effect prose rides in the description ("about to consume …")
    # plus the "On consumption" field
    assert "about to consume **`1` Pog Frog**" in (
        confirm_embed.description or ""
    )
    assert [field.name for field in confirm_embed.fields] == [
        "On consumption",
        "Seasonal Exp",
        "Status",
    ]
    consumption = next(
        field
        for field in confirm_embed.fields
        if field.name == "On consumption"
    )
    assert "Grants **30** seasonal exp." in consumption.value
    # the exp preview: a fresh member's seasonal exp now (0) -> +30 for one
    # pog — predicted from the same oracle the consume glue grants
    exp_field = next(
        field
        for field in confirm_embed.fields
        if field.name == "Seasonal Exp"
    )
    assert exp_field.value == "**`0`** -> **`30`**"
    # the resulting-status preview: the item's granted status prose
    status_field = next(
        field for field in confirm_embed.fields if field.name == "Status"
    )
    assert status_field.value == (
        "For 1 hour, a **1%** chance the bot reacts to your messages "
        "with the froggers emoji (10s cooldown)."
    )


async def test_inventory_consume_confirmation_previews_amount_scaled_exp(
    full_bot: CazzuBot,
) -> None:
    """Consuming more than one unit scales the exp preview (amount × unit)."""
    await full_bot.inventory.add(424242, "frog:basic:normal", 3)

    task = asyncio.create_task(
        run_slash(
            full_bot,
            "inventory consume",
            options={"slot": 1, "amount": 2},
            user_id=424242,
            timeout=10.0,
        )
    )
    buttons = await wait_for_menu(full_bot)
    press = await press_button(
        full_bot,
        custom_id=buttons["Yes"],
        message_id=555,
        user_id=424242,
    )
    result = await task
    assert press.exceptions == []
    assert result.exceptions == []

    first_response = result.first_response
    assert first_response is not None
    confirm_embed = first_response.get("embed")
    assert confirm_embed is not None
    exp_field = next(
        field
        for field in confirm_embed.fields
        if field.name == "Seasonal Exp"
    )
    # fresh member: 0 -> 20 (2 × basic's 10 exp); no Status (basic grants none)
    assert exp_field.value == "**`0`** -> **`20`**"
    assert [field.name for field in confirm_embed.fields] == [
        "On consumption",
        "Seasonal Exp",
    ]


async def test_inventory_consume_exp_item_shows_exp_before_after(
    full_bot: CazzuBot,
) -> None:
    """Consuming an exp-granting item reports seasonal exp before/after.

    The "Seasonal Exp" field shows the member's seasonal exp summed from
    the exp logs (the metric the consume glue writes) before and after —
    read both sides in the test to avoid hardcoding the season. A fresh
    member consuming one pog (30 exp) goes 0 -> 30.
    """
    from core.utils import month2season
    from plugins.experience import db as exp_db

    now = pendulum.now("UTC")
    before = await exp_db.seasonal_exp(
        full_bot.db, 424242, now.year, month2season(now.month)
    )
    await full_bot.inventory.add(424242, "frog:pog:normal", 2)

    (
        _confirm_embed,
        final_embed,
    ) = await _consume_confirmation_and_final_embeds(full_bot)

    after = await exp_db.seasonal_exp(
        full_bot.db, 424242, now.year, month2season(now.month)
    )
    assert after == before + 30
    exp_field = next(
        field
        for field in final_embed.fields
        if field.name == "Seasonal Exp"
    )
    assert exp_field.value == f"**`{before}`** -> **`{after}`**"


async def test_inventory_consume_classy_final_embed_shows_role_status(
    full_bot: CazzuBot,
) -> None:
    """A classy consume shows the role-grant status's prose in the final
    embed (the resulting status read back from the live contribution)."""
    await full_bot.inventory.add(424242, "frog:classy:normal", 1)

    (
        _confirm_embed,
        final_embed,
    ) = await _consume_confirmation_and_final_embeds(full_bot)

    status_field = next(
        field for field in final_embed.fields if field.name == "Status"
    )
    assert status_field.value == "Grants the **Classy** role for 3 hours."


async def test_inventory_consume_remains_final_embed_has_no_status(
    full_bot: CazzuBot,
) -> None:
    """An item that grants no status (Frog Remains) shows no Status field —
    the "if any" guard keeps the effects + exp + result fields only."""
    await full_bot.inventory.add(424242, "remains", 3)

    (
        _confirm_embed,
        final_embed,
    ) = await _consume_confirmation_and_final_embeds(full_bot)

    assert [field.name for field in final_embed.fields] == [
        "On consumption",
        "Seasonal Exp",
        "Resulting Frog Remains",
    ]
    # the remains' own flat exp still reports (3 per unit, fresh member)
    exp_field = next(
        field
        for field in final_embed.fields
        if field.name == "Seasonal Exp"
    )
    assert exp_field.value == "**`0`** -> **`3`**"
