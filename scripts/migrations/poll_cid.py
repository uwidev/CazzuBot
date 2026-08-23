"""Migration: add the poll message channel (``cid``) column.

The ``poll`` table gains ``cid`` — the channel hosting the poll's message
— so open/close can add/remove the vote button on that message. Existing
poll rows keep ``cid`` NULL (their buttons can only be edited after the
poll is re-sent). The column is appended last so the on-disk column order
matches the plugin's CREATE TABLE exactly (the boot-time schema guard
compares column order).

Idempotent: ``needs_migration`` is False once ``poll.cid`` exists (or the
table is absent). Run through ``scripts/migrate.py`` (all pending) or the
thin wrapper ``scripts/migrate_poll_cid.py``; dry-run by default,
``--commit`` to write, backup before mutation, bot stopped.

Call graph: ``MIGRATION`` registers this module with the shared harness;
``main()`` is gone — the wrapper delegates to ``wrapper_main``. Tests drive
``needs_migration`` / ``plan`` / ``migrate`` / ``verify`` directly against
a temp DB.
"""

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration


@dataclass(frozen=True, slots=True)
class PollPlan:
    """What the migration found — the dry-run report."""

    rows: int  # poll rows that will keep cid NULL


def _has_cid(conn: sqlite3.Connection) -> bool:
    """True when the ``poll`` table already has a ``cid`` column."""
    rows = conn.execute("PRAGMA table_info(poll)").fetchall()
    return any(row[1] == "cid" for row in rows)


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True when ``poll`` exists without a ``cid`` column.

    The idempotence gate: after the migration (or on a DB that never had
    the table / already carries the column) this is False.
    """
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    return "poll" in tables and not _has_cid(conn)


def plan(conn: sqlite3.Connection) -> PollPlan:
    """Read-only count of poll rows (the dry-run report)."""
    (rows,) = conn.execute("SELECT COUNT(*) FROM poll").fetchone()
    return PollPlan(rows=rows)


def migrate(conn: sqlite3.Connection) -> PollPlan:
    """Add ``poll.cid`` in one transaction; returns what it did."""
    before = plan(conn)
    conn.execute("BEGIN")
    try:
        conn.execute("ALTER TABLE poll ADD COLUMN cid INTEGER")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


def verify(conn: sqlite3.Connection) -> None:
    """Post-commit check: the column must be present."""
    assert _has_cid(conn), "ALTER TABLE did not add cid"


MIGRATION = Migration(
    id="001_poll_cid",
    doc="add the poll message channel column (poll.cid)",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        f"add poll.cid ({p.rows} existing poll row(s) keep NULL)"
    ),
    migrate=migrate,
    verify=verify,
)
