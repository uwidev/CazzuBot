"""Frogs repository (db) layer — species catalog + inventory."""

from __future__ import annotations

import pendulum

from core.bot import CazzuBot
from core.models import FrogState, FrogItemKey
from plugins.frogs import db as frog_db

_UID = 424242


async def test_inventory_freeze_and_capture_log(bot: CazzuBot) -> None:
    now = pendulum.now("UTC")
    await frog_db.modify_inventory(
        bot.db, _UID, FrogItemKey.BASIC, FrogState.NORMAL, 3
    )
    await frog_db.modify_inventory(
        bot.db, _UID, FrogItemKey.BASIC, FrogState.FROZEN, 2
    )
    assert (
        await frog_db.get_inventory(bot.db, _UID, FrogItemKey.BASIC) == 3
    )
    assert (
        await frog_db.get_inventory(
            bot.db, _UID, FrogItemKey.BASIC, FrogState.FROZEN
        )
        == 2
    )

    await frog_db.modify_capture(bot.db, _UID, modify=5)
    await frog_db.add_capture_log(
        bot.db, _UID, now, waited_for=1.5, species_key=FrogItemKey.BASIC
    )
    f_ranked = await frog_db.seasonal_ranked(
        bot.db, now.year, (now.month - 1) // 3
    )
    assert f_ranked[0][2] == 1, f_ranked

    await frog_db.season_reset_frogs(bot.db)
    assert (
        await frog_db.get_inventory(bot.db, _UID, FrogItemKey.BASIC) == 0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, _UID, FrogItemKey.BASIC, FrogState.FROZEN
        )
        == 5
    )


async def test_freeze_frogs_for_user_scoped_to_one_user(
    bot: CazzuBot,
) -> None:
    """The per-user freeze moves ONLY the target user's normal stacks.

    Mirrors ``season_reset_frogs`` semantics (normal -> frozen per
    species, merging into existing frozen) but scoped to one user: the
    other user's normal stacks and both users' Frog Remains stay put.
    """
    # two users hold the same normal stacks; user 1 also has a pre-frozen
    # Pog (merge), and both hold Frog Remains (not a frog — untouched)
    for uid in (1, 2):
        for key in (
            FrogItemKey.BASIC,
            FrogItemKey.POG,
            FrogItemKey.FROGGERS,
            FrogItemKey.CLASSY,
        ):
            await frog_db.modify_inventory(
                bot.db, uid, key, FrogState.NORMAL, 2
            )
        await bot.inventory.add(uid, "remains", 4)
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.POG, FrogState.FROZEN, 1
    )

    moved = await frog_db.freeze_frogs_for_user(bot.db, 1)

    # the summary reports each frozen species + quantity, SPECIES order
    assert moved == [
        (FrogItemKey.BASIC, 2),
        (FrogItemKey.POG, 2),
        (FrogItemKey.FROGGERS, 2),
        (FrogItemKey.CLASSY, 2),
    ], moved
    # user 1: every normal stack froze; the pre-frozen Pog merged to 3
    for key in (
        FrogItemKey.BASIC,
        FrogItemKey.FROGGERS,
        FrogItemKey.CLASSY,
    ):
        assert await frog_db.get_inventory(bot.db, 1, key) == 0
        assert (
            await frog_db.get_inventory(bot.db, 1, key, FrogState.FROZEN)
            == 2
        )
    assert await frog_db.get_inventory(bot.db, 1, FrogItemKey.POG) == 0
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.POG, FrogState.FROZEN
        )
        == 3
    )
    assert await bot.inventory.get(1, "remains") == 4
    # user 2: untouched, including their Frog Remains
    for key in (
        FrogItemKey.BASIC,
        FrogItemKey.POG,
        FrogItemKey.FROGGERS,
        FrogItemKey.CLASSY,
    ):
        assert await frog_db.get_inventory(bot.db, 2, key) == 2
        assert (
            await frog_db.get_inventory(bot.db, 2, key, FrogState.FROZEN)
            == 0
        )
    assert await bot.inventory.get(2, "remains") == 4


async def test_freeze_frogs_for_user_idempotent_skips_cluster(
    bot: CazzuBot,
) -> None:
    """Re-freezing is a no-op, and a Cluster stack is never touched."""
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.BASIC, FrogState.NORMAL, 3
    )
    await frog_db.modify_inventory(
        bot.db, 1, FrogItemKey.BASIC, FrogState.FROZEN, 2
    )
    # a stray Cluster stack (never granted in play — no item) must stay
    await bot.db.execute(
        "INSERT OR IGNORE INTO inventory (uid, item, qty) VALUES (?, ?, ?)",
        1,
        "frog:cluster:normal",
        9,
    )

    first = await frog_db.freeze_frogs_for_user(bot.db, 1)
    second = await frog_db.freeze_frogs_for_user(bot.db, 1)

    assert first == [(FrogItemKey.BASIC, 3)]
    assert second == []
    assert await frog_db.get_inventory(bot.db, 1, FrogItemKey.BASIC) == 0
    assert (
        await frog_db.get_inventory(
            bot.db, 1, FrogItemKey.BASIC, FrogState.FROZEN
        )
        == 5
    )
    val = await bot.db.fetchval(
        "SELECT qty FROM inventory WHERE uid = 1 AND item = ?",
        "frog:cluster:normal",
    )
    assert val == 9


async def test_inventory_rows(bot: CazzuBot) -> None:
    """Per-species inventory rows drive the profile rendering."""
    await frog_db.modify_inventory(
        bot.db, _UID, FrogItemKey.BASIC, FrogState.NORMAL, 2
    )
    assert await frog_db.total_inventory(bot.db, _UID) == 2
    rows = await frog_db.inventory_rows(bot.db, _UID)
    assert rows == [(FrogItemKey.BASIC, FrogState.NORMAL, 2)], rows


async def test_discovered_species_is_lifetime_and_deduped(
    bot: CazzuBot,
) -> None:
    """The collection book's discovery set: distinct captured species.

    Discovery derives from the capture log, not holdings, so a species
    stays discovered after the quarterly freeze and after its frogs are
    consumed. A log row whose key is no longer a registered species is
    ignored instead of raising.
    """
    now = pendulum.now("UTC")
    for key in (FrogItemKey.BASIC, FrogItemKey.POG, FrogItemKey.BASIC):
        await frog_db.add_capture_log(
            bot.db, _UID, now, waited_for=1.0, species_key=key
        )
    await bot.db.execute(
        """
		INSERT INTO member_frog_log (uid, type, at, waited_for)
		VALUES (?, ?, ?, ?)
		""",
        _UID,
        "ancient",
        now.isoformat(),
        1.0,
    )

    assert await frog_db.discovered_species(bot.db, _UID) == {
        FrogItemKey.BASIC,
        FrogItemKey.POG,
    }
    # another member's captures never leak into this book
    assert await frog_db.discovered_species(bot.db, _UID + 1) == set()


async def test_spawn_roundtrip_typed(bot: CazzuBot) -> None:
    """Typed row models construct from real rows (drift catches renames)."""
    await frog_db.upsert_spawn(bot.db, 123, 300, 60, 0.2)
    spawns = await frog_db.get_spawns(bot.db)
    assert len(spawns) == 1, spawns
    assert spawns[0].interval == 300 and spawns[0].fuzzy == 0.2
