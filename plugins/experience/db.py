"""Experience plugin — message exp, membership card, leaderboards, resync.

Single-guild port of v1's ``ext/experience.py`` + ``src/db/member_exp.py`` +
``src/db/member_exp_log.py``. Exp events are logged per-message with timestamps;
seasonal totals are summed from the log; lifetime is precomputed on the member.

The ladder is **chatting-only** (2026-09 decision): every reader here sums
``source = 'message'`` rows and ignores the rest. ``member_exp_log`` keeps
its FROG rows — the ``source`` column exists for exactly this — so the
history stays intact and readable by a future frog-side reader, which is
the only thing allowed to read them.
"""

from dataclasses import dataclass

import pendulum

from core.db import Database
from core.models import MemberExpLogSourceEnum
from core.utils import rank_rows, season_bounds

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

# The chat ladder's row filter: exp earned by chatting. FROG rows (frog
# consumes, historical) stay in the log but never feed a reader below.
_CHAT_SOURCE = MemberExpLogSourceEnum.MESSAGE.value


@dataclass(slots=True)
class MemberExp:
    """One ``member_exp`` row (``cdr`` is the exp cooldown expiry, UTC)."""

    uid: int
    lifetime: int
    msg_cnt: int
    cdr: pendulum.DateTime | None


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
    """Log one exp event with its ``source`` and timestamp.

    Only the default MESSAGE source feeds the chat readers above; other
    sources are inert history.
    """
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
    """All members' *chat* exp in a season, ranked: [(rank, uid, exp)]."""
    start, end = season_bounds(year, season)
    rows = await db.fetchall(
        """
		SELECT uid, SUM(exp) AS exp
		FROM member_exp_log
		WHERE at >= ? AND at < ? AND source = ?
		GROUP BY uid
		ORDER BY exp DESC
		""",
        start,
        end,
        _CHAT_SOURCE,
    )
    return rank_rows([dict(r) for r in rows], "exp")


async def seasonal_exp(
    db: Database, uid: int, year: int, season: int
) -> int:
    """A member's *chat* exp earned within a single season."""
    start, end = season_bounds(year, season)
    val = await db.fetchval(
        """
		SELECT COALESCE(SUM(exp), 0)
		FROM member_exp_log
		WHERE uid = ? AND at >= ? AND at < ? AND source = ?
		""",
        uid,
        start,
        end,
        _CHAT_SOURCE,
    )
    return int(val or 0)


async def seasonal_total_members(
    db: Database, year: int, season: int
) -> int:
    """How many members earned *chat* exp within a season.

    The percentile denominator: a member whose only rows are FROG ones has
    no chat exp and must not inflate it.
    """
    start, end = season_bounds(year, season)
    val = await db.fetchval(
        """
		SELECT COUNT(DISTINCT uid)
		FROM member_exp_log
		WHERE at >= ? AND at < ? AND source = ?
		""",
        start,
        end,
        _CHAT_SOURCE,
    )
    return int(val or 0)


async def lifetime_ranked(db: Database) -> list[tuple[int, int, int]]:
    """All members' lifetime exp, ranked: [(rank, uid, exp)]."""
    rows = await db.fetchall(
        "SELECT uid, lifetime AS exp FROM member_exp ORDER BY lifetime DESC"
    )
    return rank_rows([dict(r) for r in rows], "exp")


async def total_members(db: Database) -> int:
    """How many members have a lifetime-exp row.

    The lifetime percentile denominator (see
    :func:`seasonal_total_members`): counted from ``member_exp`` — the
    table :func:`lifetime_ranked` boards — so the denominator is the
    board's own population, the way ``plugins.frogs.db.total_members``
    counts ``member_frog`` for the capture permit. Counting the log
    instead counted members who hold no row (1,299 of them in the live
    DB) and scanned every log row, which overran Discord's 3s response
    window and made the lifetime card answer too late to be accepted.
    """
    val = await db.fetchval("SELECT COUNT(*) FROM member_exp")
    return int(val or 0)


async def reset_all_msg_cnt(db: Database) -> None:
    """Daily reset: every member's message count restarts at 1."""
    await db.execute("UPDATE member_exp SET msg_cnt = 1")


async def reset_all_cdr(db: Database) -> None:
    """Daily reset: everyone's exp cooldown expires immediately."""
    await db.execute("UPDATE member_exp SET cdr = NULL")


async def sync_with_exp_logs(db: Database) -> None:
    """Rebuild lifetime exp from the sum of every *chat* exp log row.

    FROG rows are deliberately excluded, so this is the pass that drops
    pre-decoupling frog exp out of lifetime (seasonal already reads
    chat-only live). Members with no message rows land at 0.
    """
    await db.execute(
        """
		UPDATE member_exp
		SET lifetime = (
			SELECT COALESCE(SUM(exp), 0)
			FROM member_exp_log
			WHERE member_exp_log.uid = member_exp.uid
			  AND member_exp_log.source = ?
		)
		""",
        _CHAT_SOURCE,
    )
