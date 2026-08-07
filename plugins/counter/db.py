"""Counter plugin — repository layer for the "baka button" counter.

Single-guild port of v1's ``src/db/counter.py``. Each registered counter
message is one ``counter`` row; the ``counter_baka`` rows track who pressed
the button most recently (for the footer).
"""

from cazzubot.db import Database

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS counter (
		mid   INTEGER PRIMARY KEY,
		count INTEGER NOT NULL DEFAULT 0
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS counter_baka (
		mid        INTEGER NOT NULL,
		uid        INTEGER NOT NULL,
		name       TEXT NOT NULL,
		updated_at TEXT NOT NULL,
		PRIMARY KEY (mid, uid)
	)
	""",
]


async def create(db: Database, mid: int) -> None:
    await db.execute(
        "INSERT OR IGNORE INTO counter (mid, count) VALUES (?, 0)", mid
    )


async def bump_count(db: Database, mid: int) -> int | None:
    """Increment the counter; ``None`` if no such counter exists."""
    await db.execute(
        "UPDATE counter SET count = count + 1 WHERE mid = ?", mid
    )
    row = await db.fetchone("SELECT count FROM counter WHERE mid = ?", mid)
    return row["count"] if row else None


async def record_baka(
    db: Database, mid: int, uid: int, name: str, updated_at: str
) -> None:
    await db.execute(
        "INSERT OR REPLACE INTO counter_baka (mid, uid, name, updated_at)"
        + " VALUES (?, ?, ?, ?)",
        mid,
        uid,
        name,
        updated_at,
    )


async def recent_bakas(db: Database, mid: int) -> list[str]:
    rows = await db.fetchall(
        "SELECT name FROM counter_baka WHERE mid = ?"
        + " ORDER BY updated_at DESC",
        mid,
    )
    return [r["name"] for r in rows]


async def clear_bakas(db: Database, mid: int) -> None:
    await db.execute("DELETE FROM counter_baka WHERE mid = ?", mid)


async def all_mids(db: Database) -> list[int]:
    rows = await db.fetchall("SELECT mid FROM counter")
    return [int(r["mid"]) for r in rows]
