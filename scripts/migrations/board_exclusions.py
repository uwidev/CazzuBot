"""Migration: add the ``board_exclusions`` table (board v2 slice C).

The exclusions table keeps one source MESSAGE off the board (reaction
toggle — owner or a mod role). Unlike the slice-A ``board`` rebuild this
is a purely NEW table with no legacy data to port: a boot would also
create it via ``CREATE TABLE IF NOT EXISTS``, so this migration exists to
make the schema change explicit and offline-appliable through the shared
runner (bot stopped, backup before write), mirroring the ops story of the
rest of the board v2 chain. The DDL mirrors ``plugins/board/db.py``
exactly so the boot-time schema guard sees an identical shape.

Idempotent: ``needs_migration`` is False once ``board_exclusions`` exists
(or the board plugin never ran). Run through ``scripts/migrate.py`` (all
pending) — dry-run by default, ``--commit`` to write. No thin wrapper:
precedent is ``status_contribution`` / ``frog_species_cleanup``.

Call graph: ``MIGRATION`` registers this module with the shared harness;
tests drive ``needs_migration`` / ``migrate`` directly against a temp DB.
"""

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration

# Mirrors plugins/board/db.py exactly (column order + PK constraint).
EXCLUSIONS_DDL = """
CREATE TABLE IF NOT EXISTS board_exclusions (
    message_id INTEGER PRIMARY KEY,
    created_by INTEGER NOT NULL,
    created_at TEXT NOT NULL
)
"""


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """What the migration found — the dry-run report (no data to move)."""

    created: bool  # True when the table was absent


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (name,),
    ).fetchone()
    return row is not None


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True when a real board DB lacks ``board_exclusions``.

    Gated on the ``board`` table existing (the board plugin ran there) so
    a fresh DB that has never had the board is skipped like the other
    shape-gated migrations.
    """
    return _has_table(conn, "board") and not _has_table(
        conn, "board_exclusions"
    )


def plan(conn: sqlite3.Connection) -> MigrationPlan:
    """Read-only report: whether the table exists yet."""
    return MigrationPlan(created=needs_migration(conn))


def migrate(conn: sqlite3.Connection) -> MigrationPlan:
    """Create the table in one transaction; returns what it did."""
    report = plan(conn)
    conn.execute("BEGIN")
    try:
        conn.execute(EXCLUSIONS_DDL)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return report


def verify(conn: sqlite3.Connection) -> None:
    """Post-commit check: the table exists with the right columns."""
    assert _has_table(conn, "board_exclusions"), "create did not run"
    cols = {
        r[1] for r in conn.execute("PRAGMA table_info(board_exclusions)")
    }
    assert {"message_id", "created_by", "created_at"} <= cols


MIGRATION = Migration(
    id="010_board_exclusions",
    doc="add the board_exclusions table (reaction-toggle curation)",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        "board_exclusions table created"
        if p.created
        else "board_exclusions already present — nothing to do"
    ),
    migrate=migrate,
    verify=verify,
)
