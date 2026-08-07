"""Experience repository (db) layer — ported from scripts/functest.py."""

from __future__ import annotations

import pendulum

from cazzubot.bot import CazzuBot
from plugins.experience import db as exp_db

_UID = 424242


async def test_exp_log_and_seasonal_ranked(bot: CazzuBot) -> None:
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot.db, _UID)
    await exp_db.add_exp_log(bot.db, _UID, 50, now)
    await exp_db.add_exp_log(bot.db, _UID, 30, now.add(seconds=1))
    await exp_db.add_exp_log(bot.db, 777, 100, now)

    member = await exp_db.get_member_exp(bot.db, _UID)
    assert member is not None and member.lifetime == 0  # not synced yet

    seasonal = await exp_db.seasonal_exp(
        bot.db, _UID, now.year, (now.month - 1) // 3
    )
    assert seasonal == 80
    ranked = await exp_db.seasonal_ranked(
        bot.db, now.year, (now.month - 1) // 3
    )
    assert ranked[0] == (1, 777, 100) and ranked[1][0] == 2


async def test_sync_with_exp_logs(bot: CazzuBot) -> None:
    now = pendulum.now("UTC")
    await exp_db.add_member_exp(bot.db, _UID)
    await exp_db.add_exp_log(bot.db, _UID, 50, now)
    await exp_db.sync_with_exp_logs(bot.db)
    member = await exp_db.get_member_exp(bot.db, _UID)
    assert member is not None and member.lifetime == 50


async def test_update_member_exp(bot: CazzuBot) -> None:
    await exp_db.add_member_exp(bot.db, _UID)
    await exp_db.update_member_exp(
        bot.db,
        _UID,
        lifetime=80,
        msg_cnt=5,
        cdr=pendulum.now("UTC").add(seconds=15),
    )
    member = await exp_db.get_member_exp(bot.db, _UID)
    assert member is not None and member.msg_cnt == 5
