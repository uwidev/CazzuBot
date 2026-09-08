"""Board plugin — repository layer.

One ``board`` row per scraped image: the message's post time (ISO-8601
UTC), the source channel + message (a row always knows where it came
from — every read is week × channel, never an aggregate), the CDN
attachment url (downloadable without API calls, globally unique so
re-scrapes are idempotent), the canonical message link (for the grid
post's hyperlinks), and a content hash for within-week dedup. Weeks are
derived from ``ts`` via range queries — no week column.

The board is ONE channel per week ("pointer"); rows scraped from other
channels are stored but inert — they can never leak into a post because
every read takes a ``channel_id``.
"""

from dataclasses import dataclass

from core.db import Database

SCHEMA = [
    """
	CREATE TABLE IF NOT EXISTS board (
		id         INTEGER PRIMARY KEY AUTOINCREMENT,
		ts         TEXT NOT NULL,
		channel_id INTEGER NOT NULL,
		message_id INTEGER NOT NULL,
		image_url  TEXT NOT NULL UNIQUE,
		msg_url    TEXT NOT NULL,
		sha256     TEXT NOT NULL
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
    channel_id: int
    message_id: int
    image_url: str
    msg_url: str
    sha256: str


async def add_image(
    db: Database,
    ts: str,
    image_url: str,
    msg_url: str,
    sha256: str,
    channel_id: int,
    message_id: int,
) -> bool:
    """Record one image; False when the url was already scraped."""
    rowcount = await db.execute(
        """
		INSERT OR IGNORE INTO board (
			ts, channel_id, message_id, image_url, msg_url, sha256
		)
		VALUES (?, ?, ?, ?, ?, ?)
		""",
        ts,
        channel_id,
        message_id,
        image_url,
        msg_url,
        sha256,
    )
    return rowcount > 0


async def has_sha_in_week(
    db: Database,
    sha256: str,
    start: str,
    end: str,
    channel_id: int,
) -> bool:
    """True when the same image content is already in the channel's window.

    Dedup is PER-CHANNEL: the same bytes in another channel the same week
    are not a false duplicate.
    """
    row = await db.fetchone(
        """
		SELECT 1 FROM board
		WHERE sha256 = ?
		  AND ts >= ? AND ts < ?
		  AND channel_id = ?
		LIMIT 1
		""",
        sha256,
        start,
        end,
        channel_id,
    )
    return row is not None


async def get_week_images(
    db: Database, start: str, end: str, channel_id: int
) -> list[BoardRow]:
    """Rows in the half-open [start, end) window for one channel.

    The board never aggregates channels: this is week ∩ channel,
    chronological (``ORDER BY ts, id`` kept).
    """
    return await db.fetch_models(
        BoardRow,
        """
		SELECT * FROM board
		WHERE ts >= ? AND ts < ? AND channel_id = ?
		ORDER BY ts, id
		""",
        start,
        end,
        channel_id,
    )


async def delete_image(db: Database, row_id: int) -> None:
    await db.execute("DELETE FROM board WHERE id = ?", row_id)


async def latest_row(db: Database) -> BoardRow | None:
    """The most recently scraped row (incl. its source channel), if any.

    Replaces the old ``latest_ts`` (a bare timestamp): callers that need a
    default read scope use this row's ``channel_id`` alongside its ``ts``
    (the /board post "pointer").
    """
    return await db.fetch_model(
        BoardRow,
        "SELECT * FROM board ORDER BY ts DESC, id DESC LIMIT 1",
    )
