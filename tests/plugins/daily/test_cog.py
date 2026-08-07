"""Daily reset — counts/cooldowns reset + missed-run forcing."""

from __future__ import annotations

import pendulum

from cazzubot.bot import CazzuBot
from plugins.daily import DailyCog, LAST_KEY
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

    cog = bot.get_cog(DailyCog.__cog_name__)
    assert isinstance(cog, DailyCog)
    await cog.reset()

    row = await exp_db.get_member_exp(bot.db, 1)
    assert row is not None
    assert row.msg_cnt == 1
    assert row.cdr is None
    assert row.lifetime == 80  # resynced from the logs
    assert await bot.settings.get(LAST_KEY) is not None


async def test_daily_loop_skips_recent_reset(bot: CazzuBot) -> None:
    await exp_db.add_member_exp(bot.db, 1)
    await exp_db.update_member_exp(
        bot.db, 1, lifetime=10, msg_cnt=5, cdr=pendulum.now("UTC")
    )
    await bot.settings.set(LAST_KEY, pendulum.now("UTC"))

    cog = bot.get_cog(DailyCog.__cog_name__)
    assert isinstance(cog, DailyCog)
    await cog.daily_reset.coro(cog)

    row = await exp_db.get_member_exp(bot.db, 1)
    assert row is not None and row.msg_cnt == 5  # untouched
