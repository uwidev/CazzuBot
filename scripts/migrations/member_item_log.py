"""Migration: add the ``member_item_log`` table (consumption history).

The inventory plugin's append-only ledger of consume actions
(``uid``, ``item_id``, ``amount``, ``at``) — one row per successful
consume, written by ``/inventory consume`` after the item's own handler and
the stack decrement both succeeded. Nothing reads it yet (2026-09); it is
history for later features (badges, records, a possible ladder).

Like ``board_exclusions`` this is a purely NEW table with no legacy data:
a boot would also create it via ``CREATE TABLE IF NOT EXISTS``, so the
migration exists to make the schema change explicit and offline-appliable
through the shared runner (bot stopped, backup before write). The DDL
mirrors ``plugins/inventory/db.py`` exactly — column order and the
``(uid, at)`` index — so the boot-time schema guard sees an identical
shape.

Idempotent: ``needs_migration`` is False once ``member_item_log`` exists
(or the inventory store never ran there). Run through ``scripts/migrate.py``
(all pending) — dry-run by default, ``--commit`` to write. No thin wrapper:
precedent is ``status_contribution`` / ``frog_species_cleanup``.

Call graph: ``MIGRATION`` registers this module with the shared harness;
tests drive ``needs_migration`` / ``migrate`` / ``verify`` directly against
a temp DB.
"""

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration

# Mirrors plugins/inventory/db.py exactly (column order + index).
LOG_DDL = """
CREATE TABLE IF NOT EXISTS member_item_log (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    uid     INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    amount  INTEGER NOT NULL,
    at      TEXT NOT NULL
)
"""

INDEX_DDL = (
    "CREATE INDEX IF NOT EXISTS idx_item_log_uid_at "
    "ON member_item_log (uid, at)"
)


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
    """True when a real inventory DB lacks ``member_item_log``.

    Gated on the ``inventory`` table existing (the store ran there) so a
    fresh DB that has never held an item is skipped like the other
    shape-gated migrations.
    """
    return _has_table(conn, "inventory") and not _has_table(
        conn, "member_item_log"
    )


def plan(conn: sqlite3.Connection) -> MigrationPlan:
    """Read-only report: whether the table exists yet."""
    return MigrationPlan(created=needs_migration(conn))


def migrate(conn: sqlite3.Connection) -> MigrationPlan:
    """Create the table and its index in one transaction; returns what it did."""
    report = plan(conn)
    conn.execute("BEGIN")
    try:
        conn.execute(LOG_DDL)
        conn.execute(INDEX_DDL)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return report


def verify(conn: sqlite3.Connection) -> None:
    """Post-commit check: the table exists with the right columns and index."""
    assert _has_table(conn, "member_item_log"), "create did not run"
    cols = {
        r[1] for r in conn.execute("PRAGMA table_info(member_item_log)")
    }
    assert {"id", "uid", "item_id", "amount", "at"} <= cols
    indexes = {
        r[1] for r in conn.execute("PRAGMA index_list(member_item_log)")
    }
    assert "idx_item_log_uid_at" in indexes


MIGRATION = Migration(
    id="012_member_item_log",
    doc="add the member_item_log table (append-only consume history)",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        "member_item_log table created"
        if p.created
        else "member_item_log already present — nothing to do"
    ),
    migrate=migrate,
    verify=verify,
)
