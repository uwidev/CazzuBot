"""Poll plugin — repository layer.

Persistence for polls, their items, and votes. Single-guild port of v1's
``src/db/poll.py``.
"""

from dataclasses import dataclass

from cazzubot.db import Database

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS poll (
		id        INTEGER PRIMARY KEY AUTOINCREMENT,
		title     TEXT NOT NULL DEFAULT '',
		description TEXT NOT NULL DEFAULT '',
		max_vote  INTEGER NOT NULL DEFAULT 1,
		mid       INTEGER,
		open      INTEGER NOT NULL DEFAULT 0,
		cid       INTEGER
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS poll_item (
		id  INTEGER PRIMARY KEY AUTOINCREMENT,
		pid INTEGER NOT NULL
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS poll_vote (
		pid   INTEGER NOT NULL,
		iid   INTEGER NOT NULL,
		uid   INTEGER NOT NULL,
		count INTEGER NOT NULL DEFAULT 1,
		PRIMARY KEY (pid, iid, uid)
	)
	""",
]


@dataclass(slots=True)
class Poll:
    """One ``poll`` row (``mid``/``cid`` = the message hosting the vote
    button; ``cid`` is NULL for polls sent before the cid migration)."""

    id: int
    title: str
    description: str
    max_vote: int
    mid: int | None
    open: int
    cid: int | None


@dataclass(slots=True)
class PollResult:
    """Aggregate vote counts per poll item (``iid`` → ``count``)."""

    iid: int
    count: int


@dataclass(slots=True)
class PollRow:
    """Narrow rows used for view re-attachment (``id`` + ``mid``)."""

    id: int
    mid: int | None


async def add_poll(
    db: Database, title: str, description: str, max_vote: int
) -> int | None:
    return await db.execute_lastrowid(
        """
		INSERT INTO poll (title, description, max_vote)
		VALUES (?, ?, ?)
		""",
        title,
        description,
        max_vote,
    )


async def get_poll(db: Database, pid: int) -> Poll | None:
    return await db.fetch_model(
        Poll, "SELECT * FROM poll WHERE id = ?", pid
    )


async def set_mid(db: Database, pid: int, mid: int, cid: int) -> None:
    await db.execute(
        "UPDATE poll SET mid = ?, cid = ? WHERE id = ?", mid, cid, pid
    )


async def set_open(db: Database, pid: int, val: bool) -> None:
    await db.execute(
        "UPDATE poll SET open = ? WHERE id = ?", int(val), pid
    )


async def set_description(db: Database, pid: int, description: str) -> None:
    await db.execute(
        "UPDATE poll SET description = ? WHERE id = ?", description, pid
    )


async def add_items_dummy(db: Database, pid: int, n: int) -> None:
    await db.executemany(
        "INSERT INTO poll_item (pid) VALUES (?)", [(pid,)] * n
    )


async def get_items(db: Database, pid: int) -> list[int]:
    """Poll item ids, ordered (used for vote validation ranges)."""
    rows = await db.fetchall(
        "SELECT id FROM poll_item WHERE pid = ? ORDER BY id", pid
    )
    return [int(r[0]) for r in rows]


async def add_votes(
    db: Database, pid: int, iids: list[int], uid: int
) -> None:
    await db.executemany(
        """
		INSERT INTO poll_vote (pid, iid, uid) VALUES (?, ?, ?)
		ON CONFLICT (pid, iid, uid) DO UPDATE SET
			count = poll_vote.count + 1
		""",
        [(pid, iid, uid) for iid in iids],
    )


async def drop_user_on_poll(db: Database, pid: int, uid: int) -> None:
    await db.execute(
        "DELETE FROM poll_vote WHERE pid = ? AND uid = ?", pid, uid
    )


async def get_results(db: Database, pid: int) -> list[PollResult]:
    return await db.fetch_models(
        PollResult,
        """
		SELECT vote.iid, SUM(vote.count) AS count
		FROM poll_vote AS vote
		WHERE vote.pid = ?
		GROUP BY vote.iid
		ORDER BY count DESC
		""",
        pid,
    )
