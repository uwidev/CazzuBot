"""Mod repository layer — ported from scripts/functest.py."""

from __future__ import annotations

import pendulum

from cazzubot.bot import CazzuBot
from cazzubot.models import ModlogTypeEnum
from plugins.mod.db import add_log


async def test_modlog_insert(bot: CazzuBot) -> None:
    now = pendulum.now("UTC")
    await add_log(
        bot.db,
        424242,
        ModlogTypeEnum.MUTE,
        now,
        expires_on=now.add(hours=1),
        reason="test",
    )
    row = await bot.db.fetchone("SELECT * FROM modlog")
    assert row is not None
    assert row["log_type"] == "mute" and row["status"] == "active"
