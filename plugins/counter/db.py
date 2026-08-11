"""Counter plugin — repository layer for the "baka button" counter.

Each registered counter message is one ``counter`` row (unique ``id`` plus
the message id ``mid``); every button press appends one ``counter_event``
row. The count is *derived* — ``COUNT(*)`` over the events — never stored.
``counter_event`` rows may be anonymous (``uid``/``name`` NULL, epoch
``updated_at``) for presses backfilled from the pre-history aggregate count.
"""

from typing import Any

import aiosqlite

from cazzubot.db import Database

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS counter (
		id  INTEGER PRIMARY KEY AUTOINCREMENT,
		mid INTEGER NOT NULL UNIQUE
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS counter_event (
		id         INTEGER PRIMARY KEY AUTOINCREMENT,
		counter_id INTEGER NOT NULL REFERENCES counter(id) ON DELETE CASCADE,
		uid        INTEGER,
		name       TEXT,
		updated_at TEXT NOT NULL
	)
	""",
    """
	CREATE INDEX IF NOT EXISTS idx_counter_event_counter_time
	ON counter_event (counter_id, updated_at)
	""",
]


async def create(db: Database, mid: int) -> int:
    """Register a counter message; returns its unique id (idempotent by mid)."""
    await db.execute("INSERT OR IGNORE INTO counter (mid) VALUES (?)", mid)
    row = await db.fetchone("SELECT id FROM counter WHERE mid = ?", mid)
    assert row is not None
    return int(row["id"])


async def by_id(db: Database, counter_id: int) -> aiosqlite.Row | None:
    """The counter row (``id``, ``mid``) for a unique id."""
    return await db.fetchone(
        "SELECT id, mid FROM counter WHERE id = ?", counter_id
    )


async def by_mid(db: Database, mid: int) -> aiosqlite.Row | None:
    """The counter row (``id``, ``mid``) owning a message id."""
    return await db.fetchone(
        "SELECT id, mid FROM counter WHERE mid = ?", mid
    )


async def reattach(db: Database, counter_id: int, mid: int) -> bool:
    """Point an existing counter at a new message; False if id unknown.

    Used to re-create a counter whose Discord message was deleted: the
    events (and therefore the count) stay, only the message id moves.
    """
    rowcount = await db.execute(
        "UPDATE counter SET mid = ? WHERE id = ?", mid, counter_id
    )
    return rowcount > 0


async def record_event(
    db: Database,
    counter_id: int,
    uid: int | None,
    name: str | None,
    updated_at: str,
) -> None:
    """Append one press event (the only way a count grows)."""
    await db.execute(
        "INSERT INTO counter_event (counter_id, uid, name, updated_at)"
        + " VALUES (?, ?, ?, ?)",
        counter_id,
        uid,
        name,
        updated_at,
    )


async def count_by_id(db: Database, counter_id: int) -> int:
    """The counter's total — one event row per press."""
    return int(
        await db.fetchval(
            "SELECT COUNT(*) FROM counter_event WHERE counter_id = ?",
            counter_id,
        )
        or 0
    )


async def count_by_mid(db: Database, mid: int) -> int | None:
    """Event-derived total for a message; ``None`` if it is no counter."""
    row = await db.fetchone(
        "SELECT COUNT(e.id) FROM counter c"
        + " LEFT JOIN counter_event e ON e.counter_id = c.id"
        + " WHERE c.mid = ?",
        mid,
    )
    return int(row[0]) if row is not None else None


async def recent_names(
    db: Database, counter_id: int, since: str
) -> list[str]:
    """Distinct users who pressed since ``since``, most recent first.

    Anonymous (backfilled) events are excluded — the footer shows real
    names only.
    """
    rows = await db.fetchall(
        "SELECT name FROM counter_event"
        + " WHERE counter_id = ? AND updated_at >= ? AND uid IS NOT NULL"
        + " GROUP BY uid ORDER BY MAX(updated_at) DESC",
        counter_id,
        since,
    )
    return [r["name"] for r in rows if r["name"]]


async def all(db: Database) -> list[dict[str, Any]]:
    """Every counter as (``id``, ``mid``) dicts, oldest first."""
    rows = await db.fetchall("SELECT id, mid FROM counter ORDER BY id")
    return [{"id": int(r["id"]), "mid": int(r["mid"])} for r in rows]
