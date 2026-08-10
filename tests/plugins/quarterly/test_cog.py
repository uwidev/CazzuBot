"""Quarterly reset — frog freeze at the season rollover."""

from __future__ import annotations

import pendulum

from cazzubot.bot import CazzuBot
from cazzubot.models import FrogTypeEnum
from plugins.frogs import db as frog_db
from plugins.quarterly import CADENCE, QuarterlyPlugin, on_quarterly_due, reset


async def test_quarterly_reset_freezes_frogs(bot: CazzuBot) -> None:
    await frog_db.modify_frog(bot.db, 1, modify=3)

    await reset(bot)

    assert await frog_db.get_frogs(bot.db, 1) == 0  # normal drained
    assert (await frog_db.get_frogs(bot.db, 1, FrogTypeEnum.FROZEN)) == 3


async def test_quarterly_reset_is_idempotent(bot: CazzuBot) -> None:
    """Re-freezing is a no-op — safe for retries and late catch-up."""
    await frog_db.modify_frog(bot.db, 1, modify=3)

    await reset(bot)
    await reset(bot)

    assert await frog_db.get_frogs(bot.db, 1) == 0
    assert (await frog_db.get_frogs(bot.db, 1, FrogTypeEnum.FROZEN)) == 3


async def test_quarterly_due_freezes_and_rearms(bot: CazzuBot) -> None:
    """Every fire is a rollover by construction — the freeze is unconditional."""
    await frog_db.modify_frog(bot.db, 1, modify=2)

    await on_quarterly_due(bot, {})

    assert (await frog_db.get_frogs(bot.db, 1, FrogTypeEnum.FROZEN)) == 2
    # re-armed for the next season start — exactly one future-dated row
    rows = await bot.scheduler.get("quarterly")
    assert len(rows) == 1
    assert rows[0].run_at > pendulum.now("UTC").isoformat()


async def test_quarterly_on_load_arms_when_rowless(bot: CazzuBot) -> None:
    """A fresh install arms the next season boundary on boot."""
    assert await bot.scheduler.get("quarterly") == []
    await QuarterlyPlugin().on_load(bot)
    rows = await bot.scheduler.get("quarterly")
    assert len(rows) == 1
    assert rows[0].run_at == CADENCE.next_run(
        pendulum.now("UTC")
    ).isoformat()


async def test_quarterly_on_load_leaves_existing_row(bot: CazzuBot) -> None:
    """A row from a previous run is never clobbered.

    Overdue (bot was down over a season boundary): the scheduler fires
    it on boot and the freeze runs then. Future: already armed.
    """
    run_at = pendulum.now("UTC").subtract(hours=2)
    await bot.scheduler.add("quarterly", run_at)
    await QuarterlyPlugin().on_load(bot)
    rows = await bot.scheduler.get("quarterly")
    assert len(rows) == 1
    assert rows[0].run_at == run_at.isoformat()  # untouched
