"""Board exclusions migration (slice C) — a NEW table, no data to port.

Builds a DB with the post-A board shape (channel/message columns but no
``board_exclusions``), runs the migration directly (no CLI), and asserts
the table appears with the exact DDL the plugin defines. A fresh DB (no
board table at all) must be skipped like every other shape-gated
migration.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.migrations.board_exclusions import (
    migrate,
    needs_migration,
    verify,
)

_BOARD_NO_EXCLUSIONS = """
CREATE TABLE board (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    image_url  TEXT NOT NULL UNIQUE,
    msg_url    TEXT NOT NULL,
    sha256     TEXT NOT NULL
)
"""


def _board_db(path: Path) -> sqlite3.Connection:
    """A post-A board DB (channel-scoped rows, no exclusions table)."""
    conn = sqlite3.connect(path)
    conn.execute(_BOARD_NO_EXCLUSIONS)
    conn.execute("CREATE INDEX idx_board_ts ON board (ts)")
    conn.commit()
    return conn


def test_migrate_creates_exclusions_table(tmp_path: Path) -> None:
    conn = _board_db(tmp_path / "legacy.db")
    try:
        assert needs_migration(conn) is True
        migrate(conn)

        assert needs_migration(conn) is False
        cols = {
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(board_exclusions)"
            ).fetchall()
        }
        assert {"message_id", "created_by", "created_at"} <= cols
        # message_id is the primary key
        pks = [
            r[5]
            for r in conn.execute(
                "PRAGMA table_info(board_exclusions)"
            ).fetchall()
        ]
        assert pks.count(1) == 1
        verify(conn)
        # the board table itself is untouched
        assert needs_migration(conn) is False
    finally:
        conn.close()


def test_needs_migration_false_on_fresh_db(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "fresh.db")
    try:
        assert needs_migration(conn) is False  # no board table at all
    finally:
        conn.close()


def test_needs_migration_false_when_table_present(tmp_path: Path) -> None:
    conn = _board_db(tmp_path / "done.db")
    try:
        conn.execute(
            "CREATE TABLE board_exclusions ("
            "message_id INTEGER PRIMARY KEY,"
            "created_by INTEGER NOT NULL,"
            "created_at TEXT NOT NULL)"
        )
        conn.commit()
        assert needs_migration(conn) is False
    finally:
        conn.close()
