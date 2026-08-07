"""Ranks repository (db) layer — ported from scripts/functest.py."""

from __future__ import annotations

from cazzubot.bot import CazzuBot
from plugins.ranks import db as ranks_db


async def test_threshold_roundtrip_and_calc(bot: CazzuBot) -> None:
    await ranks_db.add(bot.db, 111, 5)
    await ranks_db.add(bot.db, 222, 10)
    await ranks_db.add(bot.db, 333, 20)

    thresholds = await ranks_db.get(bot.db)
    assert [t.threshold for t in thresholds] == [5, 10, 20], thresholds

    rid, idx = ranks_db.calc_min_rank(thresholds, 12)
    assert rid == 222 and idx == 1, (rid, idx)

    rid_none, _ = ranks_db.calc_min_rank(thresholds, 2)
    assert rid_none is None
