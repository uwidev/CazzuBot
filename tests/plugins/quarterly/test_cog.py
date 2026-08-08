"""Quarterly reset — frog freeze on season rollover."""

from __future__ import annotations

import pendulum

from cazzubot.bot import CazzuBot
from cazzubot.models import FrogTypeEnum
from plugins.frogs import db as frog_db
from plugins.quarterly import LAST_KEY, on_quarterly_due, reset


async def test_quarterly_reset_freezes_frogs(bot: CazzuBot) -> None:
    await frog_db.modify_frog(bot.db, 1, modify=3)

    await reset(bot)

    assert await frog_db.get_frogs(bot.db, 1) == 0  # normal drained
    assert (await frog_db.get_frogs(bot.db, 1, FrogTypeEnum.FROZEN)) == 3
    assert await bot.settings.get(LAST_KEY) is not None


async def test_quarterly_loop_freezes_on_rollover(bot: CazzuBot) -> None:
    await frog_db.modify_frog(bot.db, 1, modify=2)
    await bot.settings.set(
        LAST_KEY,
        pendulum.now("UTC").subtract(months=4).to_iso8601_string(),
    )

    await on_quarterly_due(bot, {})

    assert (await frog_db.get_frogs(bot.db, 1, FrogTypeEnum.FROZEN)) == 2
    assert len(await bot.scheduler.get("quarterly")) == 1  # re-armed


async def test_quarterly_loop_skips_same_quarter(bot: CazzuBot) -> None:
    await frog_db.modify_frog(bot.db, 1, modify=2)
    await bot.settings.set(LAST_KEY, pendulum.now("UTC"))

    await on_quarterly_due(bot, {})

    assert await frog_db.get_frogs(bot.db, 1) == 2  # untouched
