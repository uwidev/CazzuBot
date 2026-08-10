"""Daily reset — counts/cooldowns reset + row-based midnight cadence."""

from __future__ import annotations

import pendulum

from cazzubot.bot import CazzuBot
from plugins.daily import CADENCE, DailyPlugin, on_daily_due, reset
from plugins.experience import db as exp_db


async def test_daily_reset_resets_counts_and_cooldowns(
    bot: CazzuBot,
) -> None:
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot.db, 1)
    await exp_db.update_member_exp(
        bot.db, 1, lifetime=50, msg_cnt=5, cdr=now.add(hours=1)
    )
    await exp_db.add_exp_log(bot.db, 1, 80, now)

    await reset(bot)

    row = await exp_db.get_member_exp(bot.db, 1)
    assert row is not None
    assert row.msg_cnt == 1
    assert row.cdr is None
    assert row.lifetime == 80  # resynced from the logs


async def test_daily_due_resets_and_rearms(bot: CazzuBot) -> None:
    """Every fire resets (row-based: the row is the schedule)."""
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot.db, 1)
    await exp_db.update_member_exp(
        bot.db, 1, lifetime=10, msg_cnt=5, cdr=now.add(hours=1)
    )
    await bot.scheduler.add(
        "daily", pendulum.now("UTC").subtract(seconds=1)
    )

    await on_daily_due(bot, {})

    row = await exp_db.get_member_exp(bot.db, 1)
    assert row is not None and row.msg_cnt == 1  # reset ran
    # re-armed for the next midnight — exactly one future-dated row
    rows = await bot.scheduler.get("daily")
    assert len(rows) == 1
    assert rows[0].run_at > pendulum.now("UTC").isoformat()


async def test_daily_on_load_arms_when_rowless(bot: CazzuBot) -> None:
    """A fresh install arms the first midnight on boot."""
    assert await bot.scheduler.get("daily") == []
    await DailyPlugin().on_load(bot)
    rows = await bot.scheduler.get("daily")
    assert len(rows) == 1
    assert rows[0].run_at == CADENCE.next_run(
        pendulum.now("UTC")
    ).isoformat()


async def test_daily_on_load_leaves_existing_row(bot: CazzuBot) -> None:
    """A row from a previous run is never clobbered.

    Overdue (bot was down at midnight): the scheduler fires it on boot
    and the reset runs then. Future: already armed for the next midnight.
    """
    run_at = pendulum.now("UTC").subtract(hours=2)
    await bot.scheduler.add("daily", run_at)
    await DailyPlugin().on_load(bot)
    rows = await bot.scheduler.get("daily")
    assert len(rows) == 1
    assert rows[0].run_at == run_at.isoformat()  # untouched
