"""Frogs cadences — the quarterly freeze and the daily capture resync.

Both cadences are owned by the frogs plugin now (tags ``quarterly`` and
``daily.frog``); the exp half of the midnight reset lives in the
experience plugin.
"""

from __future__ import annotations

import pendulum

from cazzubot.bot import CazzuBot
from cazzubot.models import FrogState, SpeciesKey
from plugins.frogs import db as frog_db
from plugins.frogs import (
    FrogsPlugin,
    QUARTERLY_CADENCE,
    on_daily_frog_due,
    on_quarterly_due,
)


async def test_quarterly_reset_freezes_frogs(bot: CazzuBot) -> None:
    await frog_db.modify_inventory(
        bot.db, 1, SpeciesKey.LEAF_FROG, FrogState.NORMAL, 3
    )

    await on_quarterly_due(bot, {})

    assert (
        await frog_db.get_inventory(bot.db, 1, SpeciesKey.LEAF_FROG) == 0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, SpeciesKey.LEAF_FROG, FrogState.FROZEN
        )
        == 3
    )


async def test_quarterly_reset_is_idempotent(bot: CazzuBot) -> None:
    """Re-freezing is a no-op — safe for retries and late catch-up."""
    await frog_db.modify_inventory(
        bot.db, 1, SpeciesKey.LEAF_FROG, FrogState.NORMAL, 3
    )

    await on_quarterly_due(bot, {})
    await on_quarterly_due(bot, {})

    assert (
        await frog_db.get_inventory(bot.db, 1, SpeciesKey.LEAF_FROG) == 0
    )
    assert (
        await frog_db.get_inventory(
            bot.db, 1, SpeciesKey.LEAF_FROG, FrogState.FROZEN
        )
        == 3
    )


async def test_quarterly_due_freezes_and_rearms(bot: CazzuBot) -> None:
    """Every fire is a rollover by construction — the freeze is unconditional."""
    await frog_db.modify_inventory(
        bot.db, 1, SpeciesKey.LEAF_FROG, FrogState.NORMAL, 2
    )

    await on_quarterly_due(bot, {})

    assert (
        await frog_db.get_inventory(
            bot.db, 1, SpeciesKey.LEAF_FROG, FrogState.FROZEN
        )
        == 2
    )
    # re-armed for the next season start — exactly one future-dated row
    rows = await bot.scheduler.get("quarterly")
    assert len(rows) == 1
    assert rows[0].run_at > pendulum.now("UTC")


async def test_quarterly_on_load_arms_when_rowless(bot: CazzuBot) -> None:
    """A fresh install arms the next season boundary on boot."""
    assert await bot.scheduler.get("quarterly") == []
    await FrogsPlugin().on_load(bot)
    rows = await bot.scheduler.get("quarterly")
    assert len(rows) == 1
    assert rows[0].run_at == QUARTERLY_CADENCE.next_run(
        pendulum.now("UTC")
    )


async def test_quarterly_on_load_leaves_existing_row(
    bot: CazzuBot,
) -> None:
    """A row from a previous run is never clobbered.

    Overdue (bot was down over a season boundary): the scheduler fires
    it on boot and the freeze runs then. Future: already armed.
    """
    run_at = pendulum.now("UTC").subtract(hours=2)
    await bot.scheduler.add("quarterly", run_at)
    await FrogsPlugin().on_load(bot)
    rows = await bot.scheduler.get("quarterly")
    assert len(rows) == 1
    assert rows[0].run_at == run_at  # untouched


async def test_daily_frog_due_resyncs_and_rearms(bot: CazzuBot) -> None:
    """The frog half of the midnight reset: captures resync from logs."""
    now = pendulum.now("UTC")
    await frog_db.modify_capture(bot.db, 1, modify=5)  # stale count
    await frog_db.add_capture_log(
        bot.db, 1, now, waited_for=1.5, species_key=SpeciesKey.LEAF_FROG
    )
    await bot.scheduler.add(
        "daily.frog", pendulum.now("UTC").subtract(seconds=1)
    )

    await on_daily_frog_due(bot, {})

    # the resync rebuilds capture from the log count (1 row), fixing the
    # stale 5
    ranked = await frog_db.lifetime_ranked(bot.db)
    assert ranked[0][2] == 1
    rows = await bot.scheduler.get("daily.frog")
    assert len(rows) == 1
    assert rows[0].run_at > pendulum.now("UTC")
