"""Frogs plugin — token economy. DB queries.

Single-guild port of v1's ``ext/frog.py`` + ``src/frog_factory.py`` +
``src/db/member_frog.py`` + ``src/db/member_frog_log.py`` + ``src/db/frog.py``
+ ``src/db/frog_spawn.py``.
"""

import logging
from dataclasses import dataclass

import pendulum

from typing import Any

from cazzubot.db import Database
from cazzubot.settings import Settings
from cazzubot.models import FrogTypeEnum

_log = logging.getLogger(__name__)

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS member_frog (
		uid     INTEGER PRIMARY KEY,
		normal  INTEGER NOT NULL DEFAULT 0,
		frozen  INTEGER NOT NULL DEFAULT 0,
		capture INTEGER NOT NULL DEFAULT 0
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS member_frog_log (
		id         INTEGER PRIMARY KEY AUTOINCREMENT,
		uid        INTEGER NOT NULL,
		type       TEXT NOT NULL DEFAULT 'normal',
		at         TEXT NOT NULL,
		waited_for REAL
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS frog_spawn (
		cid      INTEGER PRIMARY KEY,
		interval INTEGER NOT NULL,
		persist  INTEGER NOT NULL,
		fuzzy    REAL NOT NULL
	)
	""",
]

MESSAGE_KEY = "frog.message"
ENABLED_KEY = "frog.enabled"


@dataclass(slots=True)
class Spawn:
    """One ``frog_spawn`` row: a channel's spawn cadence config."""

    cid: int
    interval: int
    persist: int
    fuzzy: float


# -- settings --------------------------------------------------------------


async def get_message(settings: Settings) -> dict[str, Any] | None:
    return await settings.get(MESSAGE_KEY)


async def set_message(settings: Settings, message: dict[str, Any]) -> None:
    await settings.set(MESSAGE_KEY, message)


async def get_enabled(settings: Settings) -> bool:
    return bool(await settings.get(ENABLED_KEY, False))


async def set_enabled(settings: Settings, val: bool) -> None:
    await settings.set(ENABLED_KEY, val)


# -- member_frog -----------------------------------------------------------


async def get_frogs(
    db: Database,
    uid: int,
    frog_type: FrogTypeEnum = FrogTypeEnum.NORMAL,
) -> int:
    val = await db.fetchval(
        f"SELECT {frog_type.value} FROM member_frog WHERE uid = ?", uid
    )
    return int(val or 0)


async def modify_frog(
    db: Database,
    uid: int,
    *,
    modify: int,
    frog_type: FrogTypeEnum = FrogTypeEnum.NORMAL,
) -> None:
    await db.execute(
        f"""
		INSERT INTO member_frog (uid, {frog_type.value})
		VALUES (?, ?)
		ON CONFLICT (uid) DO UPDATE SET
			{frog_type.value} = member_frog.{frog_type.value} + excluded.{frog_type.value}
		""",
        uid,
        modify,
    )


async def modify_capture(db: Database, uid: int, modify: int) -> None:
    await db.execute(
        """
		INSERT INTO member_frog (uid, capture)
		VALUES (?, ?)
		ON CONFLICT (uid) DO UPDATE SET
			capture = member_frog.capture + excluded.capture
		""",
        uid,
        modify,
    )


async def lifetime_ranked(db: Database) -> list[tuple[int, int, int]]:
    """All members ranked by lifetime captures: [(rank, uid, capture)]."""
    rows = await db.fetchall(
        """
		SELECT uid, capture AS cnt
		FROM member_frog
		ORDER BY capture DESC
		"""
    )
    return _ranked([dict(r) for r in rows])


async def sync_with_frog_logs(db: Database) -> None:
    """Rebuild lifetime capture counts from the frog logs."""
    await db.execute(
        """
		UPDATE member_frog
		SET capture = (
			SELECT COUNT(*)
			FROM member_frog_log
			WHERE member_frog_log.uid = member_frog.uid
		)
		"""
    )


async def freeze_frogs(db: Database) -> None:
    """Quarterly: turn every normal frog into a frozen frog."""
    await db.execute(
        """
		UPDATE member_frog
		SET frozen = frozen + normal,
			normal = 0
		"""
    )


# -- member_frog_log -------------------------------------------------------


async def add_capture_log(
    db: Database,
    uid: int,
    at: pendulum.DateTime,
    *,
    waited_for: float,
    frog_type: FrogTypeEnum = FrogTypeEnum.NORMAL,
) -> None:
    await db.execute(
        """
		INSERT INTO member_frog_log (uid, type, at, waited_for)
		VALUES (?, ?, ?, ?)
		""",
        uid,
        frog_type.value,
        at.isoformat(),
        waited_for,
    )


async def seasonal_ranked(
    db: Database, year: int, season: int
) -> list[tuple[int, int, int]]:
    """Members' captures this season, ranked: [(rank, uid, capture_count)]."""
    start = pendulum.datetime(year, 1 + 3 * season, 1, tz="UTC")
    end = start.add(months=3)
    rows = await db.fetchall(
        """
		SELECT uid, COUNT(*) AS cnt
		FROM member_frog_log
		WHERE at >= ? AND at < ?
		GROUP BY uid
		ORDER BY cnt DESC
		""",
        start.isoformat(),
        end.isoformat(),
    )
    return _ranked([dict(r) for r in rows])


async def seasonal_captures(
    db: Database, uid: int, year: int, season: int
) -> int:
    start = pendulum.datetime(year, 1 + 3 * season, 1, tz="UTC")
    end = start.add(months=3)
    val = await db.fetchval(
        """
		SELECT COUNT(*)
		FROM member_frog_log
		WHERE uid = ? AND at >= ? AND at < ?
		""",
        uid,
        start.isoformat(),
        end.isoformat(),
    )
    return int(val or 0)


async def seasonal_total_members(
    db: Database, year: int, season: int
) -> int:
    start = pendulum.datetime(year, 1 + 3 * season, 1, tz="UTC")
    end = start.add(months=3)
    val = await db.fetchval(
        """
		SELECT COUNT(DISTINCT uid)
		FROM member_frog_log
		WHERE at >= ? AND at < ?
		""",
        start.isoformat(),
        end.isoformat(),
    )
    return int(val or 0)


async def total_members(db: Database) -> int:
    val = await db.fetchval("SELECT COUNT(*) FROM member_frog")
    return int(val or 0)


# -- frog_spawn ------------------------------------------------------------


async def upsert_spawn(
    db: Database, cid: int, interval: int, persist: int, fuzzy: float
) -> None:
    await db.execute(
        """
		INSERT INTO frog_spawn (cid, interval, persist, fuzzy)
		VALUES (?, ?, ?, ?)
		ON CONFLICT (cid) DO UPDATE SET
			interval = excluded.interval,
			persist = excluded.persist,
			fuzzy = excluded.fuzzy
		""",
        cid,
        interval,
        persist,
        fuzzy,
    )


async def clear_spawns(db: Database) -> None:
    await db.execute("DELETE FROM frog_spawn")


async def get_spawns(db: Database) -> list[Spawn]:
    return await db.fetch_models(
        Spawn, "SELECT cid, interval, persist, fuzzy FROM frog_spawn"
    )


def _ranked(rows: list[dict[str, Any]]) -> list[tuple[int, int, int]]:
    """Attach RANK()-style ranks (ties share, then skip) to (uid, cnt) rows."""
    out: list[tuple[int, int, int]] = []
    prev = None
    rank = 0
    for i, row in enumerate(rows, start=1):
        if row["cnt"] != prev:
            rank = i
        out.append((rank, row["uid"], row["cnt"]))
        prev = row["cnt"]
    return out
