"""Generic /inventory through the offline driver.

The command reads the shared ledger and renders a numbered inline-emoji
grid through the per-namespace renderer registry. These tests seed real
inventory rows, run ``/inventory`` end-to-end via ``run_slash``, and assert
the rendered embed (grid slots, namespace header, empty state).
"""

from __future__ import annotations

import hikari

from cazzubot.bot import CazzuBot
from cazzubot.models import FrogState, SpeciesKey
from tests.driver import run_slash


async def _seed_frogs(bot: CazzuBot, uid: int) -> None:
    from plugins.frogs.db import FrogItem

    await bot.inventory.add(
        uid, FrogItem(SpeciesKey.LEAF_FROG, FrogState.NORMAL), 3
    )
    await bot.inventory.add(
        uid, FrogItem(SpeciesKey.LEAF_FROG, FrogState.FROZEN), 1
    )


async def test_inventory_grid_shows_numbered_slots(
    full_bot: CazzuBot,
) -> None:
    """Seeded frogs render as numbered inline-emoji grid slots."""
    await _seed_frogs(full_bot, 424242)

    result = await run_slash(full_bot, "inventory view", user_id=424242)

    assert result.exceptions == []
    assert result.response_type == hikari.ResponseType.MESSAGE_CREATE
    embed = result.first_response.get("embed")
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


async def test_inventory_empty_state(full_bot: CazzuBot) -> None:
    """A member with no holdings sees the empty state, not an error."""
    result = await run_slash(full_bot, "inventory view", user_id=424242)

    assert result.exceptions == []
    embed = result.first_response.get("embed")
    assert embed is not None
    assert embed.description is not None
    assert "empty" in embed.description
