"""Generic /inventory through the offline driver.

The commands read the shared ledger and render embeds: ``view`` as a numbered
inline-emoji grid through the item registry, ``info`` as a description card
(thumbnail from the item's asset, title the name, the description prose, then
one field per item ``field``). These tests seed real inventory rows, run the
commands end-to-end via ``run_slash``, and assert the rendered embeds.
"""

from __future__ import annotations

import hikari

from cazzubot.bot import CazzuBot
from cazzubot.models import FrogState, FrogItemKey
from tests.driver import run_slash


async def _seed_frogs(bot: CazzuBot, uid: int) -> None:
    from plugins.frogs.db import FrogItem

    await bot.inventory.add(
        uid, FrogItem(FrogItemKey.BASIC, FrogState.NORMAL), 3
    )
    await bot.inventory.add(
        uid, FrogItem(FrogItemKey.BASIC, FrogState.FROZEN), 1
    )


async def test_inventory_grid_shows_numbered_slots(
    full_bot: CazzuBot,
) -> None:
    """Seeded frogs render as numbered inline-emoji grid slots."""
    await _seed_frogs(full_bot, 424242)

    result = await run_slash(full_bot, "inventory view", user_id=424242)

    assert result.exceptions == []
    assert result.response_type == hikari.ResponseType.MESSAGE_CREATE
    first_response = result.first_response
    assert first_response is not None
    embed = first_response.get("embed")
    assert embed is not None

    # namespace header + one field per stack (ORDER BY item → frozen first);
    # each slot shows the item's own emoji icon (no label — the grid is
    # emoji-only via the item registry)
    values = [field.value for field in embed.fields]
    assert "**FROG**" in values
    assert "🐸 ×1" in values
    assert "🐸 ×3" in values
    # deterministic slot numbers on the item fields (blank = header)
    slot_names = [field.name for field in embed.fields if field.name]
    assert slot_names == ["1", "2"]


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


async def test_inventory_grid_compacts_stale_slot_away(
    full_bot: CazzuBot,
) -> None:
    """A stale stack is hidden AND compacted: slots read 1..n, never gapped.

    Reproduces the reported bug: ``frog:classy_frog:normal`` sorted between
    classy and froggers and rendered the grid as slots 1, 2, 4, 5.
    """
    await _seed_dev_like_inventory(full_bot, 424242)

    result = await run_slash(full_bot, "inventory view", user_id=424242)

    assert result.exceptions == []
    first_response = result.first_response
    assert first_response is not None
    embed = first_response.get("embed")
    assert embed is not None
    # the hidden stack never renders a slot number — no gap between 2 and 3
    slot_names = [field.name for field in embed.fields if field.name]
    assert slot_names == ["1", "2", "3", "4"]


async def test_inventory_info_cannot_reach_hidden_stack(
    full_bot: CazzuBot,
) -> None:
    """Slots compact for info too: the stale stack's would-be slot is gone."""
    await _seed_dev_like_inventory(full_bot, 424242)

    # 4 visible slots: 1=basic, 2=classy, 3=froggers, 4=pog — the Pog Frog
    # sits at 4 (it was slot 5 before compaction) ...
    embed = await _info_embed(full_bot, 424242, 4)
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
    """Published EMOJI-kind icon_assets replace the static item icons."""
    from cazzubot.assets import asset_key
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

    result = await run_slash(full_bot, "inventory view", user_id=424242)

    assert result.exceptions == []
    first_response = result.first_response
    assert first_response is not None
    embed = first_response.get("embed")
    assert embed is not None
    values = [field.value for field in embed.fields]
    assert "<:frog_basic:123456789012345678> ×3" in values
    assert "<:frog_frozen:123456789012345678> ×1" in values


async def test_inventory_empty_state(full_bot: CazzuBot) -> None:
    """A member with no holdings sees the empty state, not an error."""
    result = await run_slash(full_bot, "inventory view", user_id=424242)

    assert result.exceptions == []
    first_response = result.first_response
    assert first_response is not None
    embed = first_response.get("embed")
    assert embed is not None
    assert embed.description is not None
    assert "empty" in embed.description


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
    from cazzubot.assets import asset_key
    from plugins.frogs.assets import FrogAsset

    await _seed_frogs(full_bot, 424242)
    # publish the frozen frog's emoji asset (slot 1 = frozen, ORDER BY item)
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

    embed = await _info_embed(full_bot, 424242, 1)

    assert embed.title == "Basic Frog (Frozen)"
    assert "frozen solid" in (embed.description or "")
    assert (
        embed.thumbnail is not None
        and embed.thumbnail.url
        == "https://cdn.discordapp.com/emojis/123456789012345678.png"
    )
    # the consumption field reads the same frog_exp oracle as the grant
    assert [field.value for field in embed.fields] == [
        "Grants **3** seasonal exp."
    ]
    assert [field.name for field in embed.fields] == ["On consumption"]


async def test_inventory_info_unpublished_asset_has_no_thumbnail(
    full_bot: CazzuBot,
) -> None:
    """An unpublished icon asset renders the card without a thumbnail."""
    await _seed_frogs(full_bot, 424242)

    embed = await _info_embed(full_bot, 424242, 1)

    assert embed.title == "Basic Frog (Frozen)"
    assert embed.thumbnail is None
    assert [field.value for field in embed.fields] == [
        "Grants **3** seasonal exp."
    ]


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
