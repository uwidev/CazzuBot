"""Experience plugin — message exp, membership card, leaderboards, resync.

Single-guild port of v1's ``ext/experience.py`` + ``src/db/member_exp.py`` +
``src/db/member_exp_log.py``. Exp events are logged per-message with timestamps;
seasonal totals are summed from the log; lifetime is precomputed on the member.
"""

from dataclasses import dataclass

import pendulum

from cazzubot.db import Database
from cazzubot.models import MemberExpLogSourceEnum
from cazzubot.utils import rank_rows, season_bounds

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS member_exp (
		uid      INTEGER PRIMARY KEY,
		lifetime INTEGER NOT NULL DEFAULT 0,
		msg_cnt  INTEGER NOT NULL DEFAULT 0,
		cdr      TEXT
	)
	""",
    """
	CREATE TABLE IF NOT EXISTS member_exp_log (
		id     INTEGER PRIMARY KEY AUTOINCREMENT,
		uid    INTEGER NOT NULL,
		exp    INTEGER NOT NULL,
		at     TEXT NOT NULL,
		source TEXT NOT NULL DEFAULT 'message'
	)
	""",
    "CREATE INDEX IF NOT EXISTS idx_exp_log_uid_at ON member_exp_log (uid, at)",
]


@dataclass(slots=True)
class MemberExp:
    """One ``member_exp`` row (``cdr`` is the exp cooldown ISO timestamp)."""

    uid: int
    lifetime: int
    msg_cnt: int
    cdr: str | None


async def get_member_exp(db: Database, uid: int) -> MemberExp | None:
    """A member's ``member_exp`` row, or None."""
    return await db.fetch_model(
        MemberExp, "SELECT * FROM member_exp WHERE uid = ?", uid
    )


async def add_member_exp(
    db: Database,
    uid: int,
    *,
    lifetime: int = 0,
    msg_cnt: int = 0,
    cdr: str | None = None,
) -> None:
    """Upsert a member's exp row (INSERT-only; the row already exists on update)."""
    await db.execute(
        """
		INSERT OR IGNORE INTO member_exp (uid, lifetime, msg_cnt, cdr)
		VALUES (?, ?, ?, ?)
		""",
        uid,
        lifetime,
        msg_cnt,
        cdr,
    )


async def update_member_exp(
    db: Database,
    uid: int,
    *,
    lifetime: int,
    msg_cnt: int,
    cdr: pendulum.DateTime,
) -> None:
    """Set a member's lifetime, message count, and next exp cooldown."""
    await db.execute(
        """
		UPDATE member_exp
		SET lifetime = ?, msg_cnt = ?, cdr = ?
		WHERE uid = ?
		""",
        lifetime,
        msg_cnt,
        cdr.isoformat(),
        uid,
    )


async def add_exp_log(
    db: Database,
    uid: int,
    exp: int,
    at: pendulum.DateTime,
    *,
    source: MemberExpLogSourceEnum = MemberExpLogSourceEnum.MESSAGE,
) -> None:
    """Log one exp event with its ``source`` and timestamp."""
    await db.execute(
        """
		INSERT INTO member_exp_log (uid, exp, at, source)
		VALUES (?, ?, ?, ?)
		""",
        uid,
        exp,
        at.isoformat(),
        source.value,
    )


async def seasonal_ranked(
    db: Database, year: int, season: int
) -> list[tuple[int, int, int]]:
    """All members' exp in a season, ranked: [(rank, uid, exp)]."""
    start, end = season_bounds(year, season)
    rows = await db.fetchall(
        """
		SELECT uid, SUM(exp) AS exp
		FROM member_exp_log
		WHERE at >= ? AND at < ?
		GROUP BY uid
		ORDER BY exp DESC
		""",
        start,
        end,
    )
    return rank_rows([dict(r) for r in rows], "exp")


async def seasonal_exp(
    db: Database, uid: int, year: int, season: int
) -> int:
    """A member's exp earned within a single season."""
    start, end = season_bounds(year, season)
    val = await db.fetchval(
        """
		SELECT COALESCE(SUM(exp), 0)
		FROM member_exp_log
		WHERE uid = ? AND at >= ? AND at < ?
		""",
        uid,
        start,
        end,
    )
    return int(val or 0)


async def seasonal_total_members(
    db: Database, year: int, season: int
) -> int:
    """How many distinct members earned exp within a season."""
    start, end = season_bounds(year, season)
    val = await db.fetchval(
        """
		SELECT COUNT(DISTINCT uid)
		FROM member_exp_log
		WHERE at >= ? AND at < ?
		""",
        start,
        end,
    )
    return int(val or 0)


async def lifetime_ranked(db: Database) -> list[tuple[int, int, int]]:
    """All members' lifetime exp, ranked: [(rank, uid, exp)]."""
    rows = await db.fetchall(
        "SELECT uid, lifetime AS exp FROM member_exp ORDER BY lifetime DESC"
    )
    return rank_rows([dict(r) for r in rows], "exp")


async def total_members(db: Database) -> int:
    """How many members have an exp row."""
    val = await db.fetchval("SELECT COUNT(*) FROM member_exp")
    return int(val or 0)


async def reset_all_msg_cnt(db: Database) -> None:
    """Daily reset: every member's message count restarts at 1."""
    await db.execute("UPDATE member_exp SET msg_cnt = 1")


async def reset_all_cdr(db: Database) -> None:
    """Daily reset: everyone's exp cooldown expires immediately."""
    await db.execute("UPDATE member_exp SET cdr = NULL")


async def sync_with_exp_logs(db: Database) -> None:
    """Rebuild lifetime exp from the sum of all exp logs."""
    await db.execute(
        """
		UPDATE member_exp
		SET lifetime = (
			SELECT COALESCE(SUM(exp), 0)
			FROM member_exp_log
			WHERE member_exp_log.uid = member_exp.uid
		)
		"""
    )
