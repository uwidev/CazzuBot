"""Inventory plugin — the member item-consumption ledger.

The generic inventory store (``core/inventory.py``) counts *holdings*; this
module owns the plugin's one table, the append-only **history** of consume
actions (``member_item_log``, named after ``member_exp_log`` /
``member_frog_log``). One row per consume *action* carrying its ``amount``
— cheaper than one row per unit and still enough for per-item, per-day and
per-member aggregates; per-unit granularity would be a schema change if a
future feature ever needs it.

Nothing reads the log yet (2026-09): it exists so badges, records and a
possible consumption ladder can later be built on real history. The log
itself commits to none of that.

Call graph: ``add_item_log`` is called by the consume path
(``plugins/inventory/extension.py``) *after* the item's own consume handler
and the stack decrement both succeeded, so refusals and failed outcomes are
never logged. Reads are deferred — ``item_log_for`` exists so a future
reader crosses the model boundary through :class:`MemberItemLog`
(``fetch_models``), never a raw row.

Depends on: ``core.db``.
"""

from dataclasses import dataclass

import pendulum

from core.db import Database

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS member_item_log (
		id      INTEGER PRIMARY KEY AUTOINCREMENT,
		uid     INTEGER NOT NULL,
		item_id TEXT NOT NULL,
		amount  INTEGER NOT NULL,
		at      TEXT NOT NULL
	)
	""",
    "CREATE INDEX IF NOT EXISTS idx_item_log_uid_at ON member_item_log (uid, at)",
]


@dataclass(slots=True)
class MemberItemLog:
    """One ``member_item_log`` row: one consume action and how many units."""

    id: int
    uid: int
    item_id: str
    amount: int
    at: pendulum.DateTime


async def add_item_log(
    db: Database,
    uid: int,
    item_id: str,
    amount: int,
    at: pendulum.DateTime,
) -> None:
    """Append one consume action (``amount`` units of ``item_id``)."""
    await db.execute(
        """
		INSERT INTO member_item_log (uid, item_id, amount, at)
		VALUES (?, ?, ?, ?)
		""",
        uid,
        item_id,
        amount,
        at.isoformat(),
    )


async def item_log_for(db: Database, uid: int) -> list[MemberItemLog]:
    """A member's consume history, oldest first.

    No caller yet (reads are deferred by design) — it exists so the first
    reader gets a typed model instead of a raw row.
    """
    return await db.fetch_models(
        MemberItemLog,
        """
		SELECT id, uid, item_id, amount, at
		FROM member_item_log
		WHERE uid = ?
		ORDER BY id
		""",
        uid,
    )
