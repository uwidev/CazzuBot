"""Quarterly reset — frog freeze on season rollover."""

from __future__ import annotations

import pendulum

from cazzubot.bot import CazzuBot
from cazzubot.models import FrogTypeEnum
from plugins.frogs import db as frog_db
from plugins.quarterly import LAST_KEY, QuarterlyCog


async def test_quarterly_reset_freezes_frogs(bot: CazzuBot) -> None:
    await frog_db.modify_frog(bot.db, 1, modify=3)

    cog = bot.get_cog(QuarterlyCog.__cog_name__)
    assert isinstance(cog, QuarterlyCog)
    await cog.reset()

    assert await frog_db.get_frogs(bot.db, 1) == 0  # normal drained
    assert (await frog_db.get_frogs(bot.db, 1, FrogTypeEnum.FROZEN)) == 3
    assert await bot.settings.get(LAST_KEY) is not None


async def test_quarterly_loop_freezes_on_rollover(bot: CazzuBot) -> None:
    await frog_db.modify_frog(bot.db, 1, modify=2)
    await bot.settings.set(
        LAST_KEY,
        pendulum.now("UTC").subtract(months=4).to_iso8601_string(),
    )

    cog = bot.get_cog(QuarterlyCog.__cog_name__)
    assert isinstance(cog, QuarterlyCog)
    await cog.quarterly_reset.coro(cog)

    assert (await frog_db.get_frogs(bot.db, 1, FrogTypeEnum.FROZEN)) == 2


async def test_quarterly_loop_skips_same_quarter(bot: CazzuBot) -> None:
    await frog_db.modify_frog(bot.db, 1, modify=2)
    await bot.settings.set(LAST_KEY, pendulum.now("UTC"))

    cog = bot.get_cog(QuarterlyCog.__cog_name__)
    assert isinstance(cog, QuarterlyCog)
    await cog.quarterly_reset.coro(cog)

    assert await frog_db.get_frogs(bot.db, 1) == 2  # untouched
