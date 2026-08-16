"""Poll repository layer — ported from scripts/functest.py."""

from __future__ import annotations

from cazzubot.bot import CazzuBot
from plugins.poll.db import (
    Poll,
    PollResult,
    add_items_dummy,
    add_poll,
    add_votes,
    get_items,
    get_poll,
    get_results,
)

_UID = 424242


async def test_poll_roundtrip_and_typed_rows(bot: CazzuBot) -> None:
    pid = await add_poll(bot.db, "title", "desc", 2)
    assert pid is not None
    poll = await get_poll(bot.db, pid)
    assert (
        poll is not None
        and poll.title == "title"
        and poll.max_vote == 2
        and isinstance(poll, Poll)
    )

    await add_items_dummy(bot.db, pid, 3)
    items = await get_items(bot.db, pid)
    assert items == [1, 2, 3], items

    await add_votes(bot.db, pid, [1, 2], _UID)
    results = await get_results(bot.db, pid)
    assert len(results) == 2, results
    assert all(isinstance(r, PollResult) and r.count == 1 for r in results)

    rows = await bot.db.fetch_models(
        Poll, "SELECT * FROM poll WHERE mid IS NOT NULL"
    )
    assert rows == []
