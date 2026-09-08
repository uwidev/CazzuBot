"""Board channel-scope migration — legacy board rows (no channel/message)
→ rebuilt table with channel_id/message_id backfilled from msg_url.

Builds a temp DB in the legacy shape, runs the migration logic directly
(no CLI), and asserts the new shape — plus the acceptance criterion that
a migrated DB passes the real boot schema guard for the board plugin's
DDL and that the channel-scoped reads return the backfilled rows.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.db import Database
from plugins.board import db as board_db
from scripts.migrations.board_channel_scope import (
    migrate,
    needs_migration,
    plan,
    verify,
)
from scripts.migrations.board_exclusions import (
    migrate as migrate_exclusions,
)

_LEGACY_BOARD = """
CREATE TABLE board (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    image_url TEXT NOT NULL UNIQUE,
    msg_url   TEXT NOT NULL,
    sha256    TEXT NOT NULL
)
"""

_LEGACY_INDEX = "CREATE INDEX idx_board_ts ON board (ts)"

# (ts, image_url, msg_url, sha256) — two channels, guild 2
_LEGACY_ROWS = [
    (
        "2026-08-03T00:00:00+00:00",
        "https://example.com/a.png",
        "https://discord.com/channels/2/99/1",
        "hash-a",
    ),
    (
        "2026-08-03T00:00:00+00:00",
        "https://example.com/b.png",
        "https://discord.com/channels/2/88/5",
        "hash-b",
    ),
    (
        "2026-08-04T00:00:00+00:00",
        "https://example.com/c.png",
        "https://discord.com/channels/2/99/2",
        "hash-c",
    ),
]


def _legacy_conn(path: Path) -> sqlite3.Connection:
    """A legacy-shape DB: a board table without channel/message columns."""
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_BOARD)
    conn.execute(_LEGACY_INDEX)
    conn.executemany(
        "INSERT INTO board (ts, image_url, msg_url, sha256) "
        "VALUES (?, ?, ?, ?)",
        _LEGACY_ROWS,
    )
    conn.commit()
    return conn


def test_migrate_backfills_channel_and_message(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        plan(conn)  # dry-run report must not mutate
        assert needs_migration(conn) is True
        migrate(conn)

        assert needs_migration(conn) is False
        cols = {r[1] for r in conn.execute("PRAGMA table_info(board)")}
        assert {"channel_id", "message_id"} <= cols
        # every row backfilled from its msg_url
        rows = conn.execute(
            "SELECT msg_url, channel_id, message_id FROM board ORDER BY id"
        ).fetchall()
        assert rows == [
            ("https://discord.com/channels/2/99/1", 99, 1),
            ("https://discord.com/channels/2/88/5", 88, 5),
            ("https://discord.com/channels/2/99/2", 99, 2),
        ]
        # ids and the image_url uniqueness survive the rebuild
        urls = {
            r[0]
            for r in conn.execute("SELECT image_url FROM board").fetchall()
        }
        assert urls == {r[1] for r in _LEGACY_ROWS}
        verify(conn)
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        migrate(conn)
        # the idempotence gate: the legacy shape is gone, so the runner
        # would skip a second run entirely
        assert needs_migration(conn) is False
    finally:
        conn.close()


def test_needs_migration_false_without_legacy_shape(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(tmp_path / "fresh.db")
    try:
        assert needs_migration(conn) is False  # no tables at all
    finally:
        conn.close()


def test_migrate_refuses_unparseable_msg_url(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        conn.execute(
            "INSERT INTO board (ts, image_url, msg_url, sha256) "
            "VALUES ('2026-08-05T00:00:00+00:00', "
            "'https://example.com/bad.png', 'not-a-link', 'hash-bad')"
        )
        conn.commit()
        with pytest.raises(ValueError, match="unparseable board msg_url"):
            migrate(conn)
        # rolled back: the legacy shape is intact
        assert needs_migration(conn) is True
    finally:
        conn.close()


async def test_migrated_db_passes_schema_guard_and_scoped_reads(
    tmp_path: Path,
) -> None:
    """Acceptance: a migrated legacy DB passes verify_schema against the
    board plugin DDL, and channel-scoped reads see the backfilled rows."""
    db_path = tmp_path / "migrated.db"
    conn = _legacy_conn(db_path)
    try:
        # apply the whole board v2 chain, runner order: 009 (rebuild +
        # backfill) then 010 (the exclusions table now in board SCHEMA)
        migrate(conn)
        migrate_exclusions(conn)
    finally:
        conn.close()

    db = Database(str(db_path))
    await db.connect()
    try:
        # the boot guard would SystemExit on a schema mismatch — this
        # raises SchemaMismatchError instead, so a clean pass is proof
        await db.verify_schema(board_db.SCHEMA)

        start, end = (
            "2026-08-02T00:00:00+00:00",
            "2026-08-09T00:00:00+00:00",
        )
        rows = await board_db.get_week_images(db, start, end, 99)
        assert [r.image_url for r in rows] == [
            "https://example.com/a.png",
            "https://example.com/c.png",
        ]
        assert [r.channel_id for r in rows] == [99, 99]
        other = await board_db.get_week_images(db, start, end, 88)
        assert [r.image_url for r in other] == [
            "https://example.com/b.png"
        ]
    finally:
        await db.close()
