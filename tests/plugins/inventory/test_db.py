"""Inventory consumption ledger — append-only writes, typed reads.

The plugin's one table (``member_item_log``): one row per consume *action*
carrying its ``amount``. Reads are deferred (no command uses them yet), so
these tests are the ledger's contract: append-only, ordered by insertion,
and read back through :class:`MemberItemLog` — never a raw row.
"""

from __future__ import annotations

import pendulum

from core.bot import CazzuBot
from plugins.inventory import db as inv_db


async def test_add_item_log_appends_rows(bot: CazzuBot) -> None:
    """Two consumes append two rows with their own amount and timestamp."""
    now = pendulum.now("UTC")
    await inv_db.add_item_log(bot.db, 42, "frog:pog:normal", 2, now)
    await inv_db.add_item_log(bot.db, 42, "remains", 1, now.add(seconds=1))

    rows = await inv_db.item_log_for(bot.db, 42)
    assert [type(row) for row in rows] == [inv_db.MemberItemLog] * 2
    assert [(r.item_id, r.amount) for r in rows] == [
        ("frog:pog:normal", 2),
        ("remains", 1),
    ]
    assert all(r.uid == 42 for r in rows)
    assert rows[0].at == now and rows[1].at == now.add(seconds=1)


async def test_item_log_for_scopes_to_the_member(bot: CazzuBot) -> None:
    """One member's history never leaks another's rows."""
    now = pendulum.now("UTC")
    await inv_db.add_item_log(bot.db, 1, "frog:basic:normal", 1, now)
    await inv_db.add_item_log(bot.db, 2, "frog:classy:normal", 3, now)

    assert [r.uid for r in await inv_db.item_log_for(bot.db, 1)] == [1]
    assert await inv_db.item_log_for(bot.db, 999) == []
