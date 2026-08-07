"""Frogs repository (db) layer — ported from scripts/functest.py."""

from __future__ import annotations

import pendulum

from cazzubot.bot import CazzuBot
from cazzubot.models import FrogTypeEnum
from plugins.frogs import db as frog_db

_UID = 424242


async def test_inventory_freeze_and_capture_log(bot: CazzuBot) -> None:
    now = pendulum.now("UTC")
    await frog_db.modify_frog(bot.db, _UID, modify=3)
    await frog_db.modify_frog(
        bot.db, _UID, modify=2, frog_type=FrogTypeEnum.FROZEN
    )
    assert await frog_db.get_frogs(bot.db, _UID) == 3

    await frog_db.modify_capture(bot.db, _UID, modify=5)
    await frog_db.add_capture_log(bot.db, _UID, now, waited_for=1.5)
    f_ranked = await frog_db.seasonal_ranked(
        bot.db, now.year, (now.month - 1) // 3
    )
    assert f_ranked[0][2] == 1, f_ranked

    await frog_db.freeze_frogs(bot.db)
    assert await frog_db.get_frogs(bot.db, _UID) == 0  # normal drained
    assert (
        await frog_db.get_frogs(bot.db, _UID, FrogTypeEnum.FROZEN)
    ) == 5


async def test_spawn_roundtrip_typed(bot: CazzuBot) -> None:
    """Typed row models construct from real rows (drift catches renames)."""
    await frog_db.upsert_spawn(bot.db, 123, 300, 60, 0.2)
    spawns = await frog_db.get_spawns(bot.db)
    assert len(spawns) == 1, spawns
    assert spawns[0].interval == 300 and spawns[0].fuzzy == 0.2
