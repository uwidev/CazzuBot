"""Migration: scope ``board`` rows by source channel + message.

Board v2 (locked with owner): the board is ONE channel per week
("pointer") and never aggregates channels. Every ``board`` row must know
its source channel + message. The legacy shape has neither — both are
already derivable from ``msg_url``, which is always the canonical
``https://discord.com/channels/{guild}/{channel}/{message}`` link the
scraper builds. This migration rebuilds the table (SQLite cannot add a
NOT NULL column without a default, and a plain ALTER would leave a
``DEFAULT 0`` residue that fails the boot-time schema guard), adding
``channel_id`` + ``message_id`` and backfilling them by parsing
``msg_url``. Column order and the UNIQUE ``image_url`` + ``idx_board_ts``
index mirror ``plugins/board/db.py`` exactly so the guard passes on a
migrated DB.

Idempotent: ``needs_migration`` is False once the ``board`` table carries
``channel_id`` (or never existed). Run through ``scripts/migrate.py``
(all pending) — dry-run by default, ``--commit`` to write, backup before
mutation, bot stopped. No thin wrapper: precedent is
``status_contribution`` / ``frog_species_cleanup``, which run via the
runner only.

Call graph: ``MIGRATION`` registers this module with the shared harness;
tests drive ``needs_migration`` / ``plan`` / ``migrate`` directly against
a temp legacy DB and verify the boot schema guard accepts the result.
"""

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration

# Mirrors plugins/board/db.py exactly: the boot-time schema guard
# compares column order, defaults, constraints and the AUTOINCREMENT
# keyword, so migrated tables must match the Python DDL.
BOARD_DDL = """
CREATE TABLE board_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    image_url  TEXT NOT NULL UNIQUE,
    msg_url    TEXT NOT NULL,
    sha256     TEXT NOT NULL
)
"""

# The canonical board row link, as built by plugins/board/logic.py.
MSG_URL_PREFIX = "https://discord.com/channels/"


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """What the migration found — the dry-run report."""

    rows: int  # board rows to backfill


def _has_channel_id(conn: sqlite3.Connection) -> bool:
    """True when the ``board`` table already has a ``channel_id`` column."""
    rows = conn.execute("PRAGMA table_info(board)").fetchall()
    return any(row[1] == "channel_id" for row in rows)


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True when ``board`` exists without a ``channel_id`` column.

    The idempotence gate: after the migration (or on a DB that never had
    the table / already carries the column) this is False.
    """
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    return "board" in tables and not _has_channel_id(conn)


def plan(conn: sqlite3.Connection) -> MigrationPlan:
    """Read-only count of board rows (the dry-run report)."""
    (rows,) = conn.execute("SELECT COUNT(*) FROM board").fetchone()
    return MigrationPlan(rows=rows)


def _channel_message(msg_url: str) -> tuple[int, int]:
    """Parse ``(channel_id, message_id)`` out of a canonical msg_url.

    The scraper always builds ``https://discord.com/channels/{guild}/
    {channel}/{message}``; any other shape is a data anomaly this
    migration refuses to guess about.
    """
    rest = msg_url.removeprefix(MSG_URL_PREFIX)
    parts = rest.split("/")
    if len(parts) != 3:
        raise ValueError(f"unparseable board msg_url: {msg_url!r}")
    try:
        return int(parts[1]), int(parts[2])
    except ValueError as err:
        raise ValueError(
            f"unparseable board msg_url: {msg_url!r}"
        ) from err


def migrate(conn: sqlite3.Connection) -> MigrationPlan:
    """Rebuild ``board`` with channel/message columns, backfilled from
    ``msg_url``; returns what it did (one transaction)."""
    report = plan(conn)
    # positional access: direct test connections have no Row factory
    rows = conn.execute(
        "SELECT id, ts, image_url, msg_url, sha256 FROM board ORDER BY id"
    ).fetchall()
    conn.execute("BEGIN")
    try:
        conn.execute(BOARD_DDL)
        conn.executemany(
            "INSERT INTO board_new "
            "(id, ts, channel_id, message_id, image_url, msg_url, sha256) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    row_id,
                    ts,
                    *_channel_message(msg_url),
                    image_url,
                    msg_url,
                    sha256,
                )
                for row_id, ts, image_url, msg_url, sha256 in rows
            ],
        )
        conn.execute("DROP TABLE board")
        conn.execute("ALTER TABLE board_new RENAME TO board")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_board_ts ON board (ts)"
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return report


def verify(conn: sqlite3.Connection) -> None:
    """Post-commit check: the columns exist and every row's backfill
    matches its msg_url."""
    assert _has_channel_id(conn), "board rebuild did not add channel_id"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(board)")}
    assert "message_id" in cols, "board rebuild did not add message_id"
    for msg_url, channel_id, message_id in conn.execute(
        "SELECT msg_url, channel_id, message_id FROM board"
    ):
        assert _channel_message(msg_url) == (
            channel_id,
            message_id,
        ), f"backfill mismatch for {msg_url}"


MIGRATION = Migration(
    id="009_board_channel_scope",
    doc="scope board rows by source channel + message "
    "(channel_id/message_id backfilled from msg_url)",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        f"rebuild board with channel_id/message_id "
        f"({p.rows} row(s) backfilled from msg_url)"
    ),
    migrate=migrate,
    verify=verify,
)
