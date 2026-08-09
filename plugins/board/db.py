"""Board plugin — repository layer.

One ``board`` row per scraped image: the message's post time (ISO-8601
UTC), the CDN attachment url (downloadable without API calls, globally
unique so re-scrapes are idempotent), the canonical message link (for the
grid post's hyperlinks), and a content hash for within-week dedup. Weeks
are derived from ``ts`` via range queries — no week column.
"""

from dataclasses import dataclass

from cazzubot.db import Database

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS board (
		id        INTEGER PRIMARY KEY AUTOINCREMENT,
		ts        TEXT NOT NULL,
		image_url TEXT NOT NULL UNIQUE,
		msg_url   TEXT NOT NULL,
		sha256    TEXT NOT NULL
	)
	""",
    """
	CREATE INDEX IF NOT EXISTS idx_board_ts ON board (ts)
	""",
]


@dataclass(slots=True)
class BoardRow:
    """One scraped image (``ts`` is the message's post time, UTC ISO)."""

    id: int
    ts: str
    image_url: str
    msg_url: str
    sha256: str


async def add_image(
    db: Database,
    ts: str,
    image_url: str,
    msg_url: str,
    sha256: str,
) -> bool:
    """Record one image; False when the url was already scraped."""
    rowcount = await db.execute(
        """
		INSERT OR IGNORE INTO board (ts, image_url, msg_url, sha256)
		VALUES (?, ?, ?, ?)
		""",
        ts,
        image_url,
        msg_url,
        sha256,
    )
    return rowcount > 0


async def has_sha_in_week(
    db: Database, sha256: str, start: str, end: str
) -> bool:
    """True when the same image content is already in the window."""
    row = await db.fetchone(
        """
		SELECT 1 FROM board
		WHERE sha256 = ? AND ts >= ? AND ts < ?
		LIMIT 1
		""",
        sha256,
        start,
        end,
    )
    return row is not None


async def get_week_images(
    db: Database, start: str, end: str
) -> list[BoardRow]:
    """Rows in the half-open [start, end) window, chronological."""
    return await db.fetch_models(
        BoardRow,
        """
		SELECT * FROM board WHERE ts >= ? AND ts < ?
		ORDER BY ts, id
		""",
        start,
        end,
    )


async def delete_image(db: Database, row_id: int) -> None:
    await db.execute("DELETE FROM board WHERE id = ?", row_id)


async def latest_ts(db: Database) -> str | None:
    """Post time of the most recently scraped image, if any."""
    row = await db.fetchone("SELECT MAX(ts) FROM board")
    if row is None or row[0] is None:
        return None
    return str(row[0])
