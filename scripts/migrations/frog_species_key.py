"""Migration: re-key frog data from ``leaf_frog`` to ``basic``.

The species key value changed (``FrogItemKey.BASIC = "basic"``; see
``plugins/frogs/species.py``): frog stacks written under the old value no
longer resolve. This renames both stored surfaces to the new key:

- ``inventory.item`` — ``frog:leaf_frog:<state>`` -> ``frog:basic:<state>``;
- ``member_frog_log.type`` — ``'leaf_frog'`` -> ``'basic'``. The table is
  REBUILT because its ``type`` column default changed too — a plain row
  rewrite would leave the old default and fail the boot schema guard.

Idempotent: ``needs_renaming`` is False once no legacy rows remain (or the
tables are absent). Run through ``scripts/migrate.py`` (all pending) or
the thin wrapper ``scripts/rename_frog_species_key.py``; dry-run by
default, ``--commit`` to write, backup before mutation, bot stopped.

Call graph: ``MIGRATION`` registers this module with the shared harness;
tests drive ``needs_renaming`` / ``plan`` / ``migrate`` directly against a
temp DB and boot the bot on the result (schema guard acceptance).
"""

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration

# mirrors plugins/frogs/species.py FrogItemKey.BASIC.value
LEGACY_KEY = "leaf_frog"
CURRENT_KEY = "basic"

# The generic inventory DDL, mirroring cazzubot/inventory.py exactly: the
# boot-time schema guard compares column order and defaults, so migrated
# tables must match the Python DDL. Frog stacks are items derived from
# FrogItem.key (plugins/frogs/db.py): "frog:<species>:<state>".
INVENTORY_DDL = """
CREATE TABLE IF NOT EXISTS inventory (
    uid  INTEGER NOT NULL,
    item TEXT NOT NULL,
    qty  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (uid, item)
)
"""

# member_frog_log is REBUILT (not altered) because its ``type`` default
# changed from 'leaf_frog' to 'basic' — a plain row rewrite would leave
# the old default and fail the schema guard.
MEMBER_FROG_LOG_DDL = """
CREATE TABLE member_frog_log_new (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        INTEGER NOT NULL,
    type       TEXT NOT NULL DEFAULT 'basic',
    at         TEXT NOT NULL,
    waited_for REAL
)
"""


@dataclass(frozen=True, slots=True)
class RenamePlan:
    """What the rename found — the dry-run report."""

    inventory_rows: int  # frog stacks to re-key
    log_rows: int  # member_frog_log.type rows to rewrite


def _table_names(conn: sqlite3.Connection) -> set[str]:
    """User table names in ``conn`` (sqlite-internal ones excluded)."""
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {r[0] for r in rows if not r[0].startswith("sqlite_")}


def needs_renaming(conn: sqlite3.Connection) -> bool:
    """True when any legacy ``leaf_frog`` value remains in the database.

    Checks both stored surfaces — inventory stacks and capture-log types
    (either table may be absent on a DB that never saw the frog work).
    The idempotence gate: after the rename (or on a DB born after the key
    change) this is False.
    """
    tables = _table_names(conn)
    if "inventory" in tables:
        (item_hits,) = conn.execute(
            "SELECT COUNT(*) FROM inventory "
            + "WHERE item LIKE 'frog:leaf_frog:%'"
        ).fetchone()
        if item_hits:
            return True
    if "member_frog_log" in tables:
        (log_hits,) = conn.execute(
            "SELECT COUNT(*) FROM member_frog_log WHERE type = 'leaf_frog'"
        ).fetchone()
        if log_hits:
            return True
    return False


def plan(conn: sqlite3.Connection) -> RenamePlan:
    """Read-only counts of what :func:`migrate` would do."""
    tables = _table_names(conn)
    inventory_rows = 0
    log_rows = 0
    if "inventory" in tables:
        (inventory_rows,) = conn.execute(
            "SELECT COUNT(*) FROM inventory "
            + "WHERE item LIKE 'frog:leaf_frog:%'"
        ).fetchone()
    if "member_frog_log" in tables:
        (log_rows,) = conn.execute(
            "SELECT COUNT(*) FROM member_frog_log WHERE type = 'leaf_frog'"
        ).fetchone()
    return RenamePlan(inventory_rows=inventory_rows, log_rows=log_rows)


def migrate(conn: sqlite3.Connection) -> RenamePlan:
    """Apply the rename in one transaction; returns what it did.

    Steps: re-key ``inventory.item`` from ``frog:leaf_frog:*`` to
    ``frog:basic:*``; rebuild ``member_frog_log`` with the new DDL
    (rewriting ``'leaf_frog'`` types to ``'basic'`` during the copy).
    Callers gate on :func:`needs_renaming` — with no legacy rows there is
    nothing to do.
    """
    before = plan(conn)
    conn.execute("BEGIN")
    try:
        if "inventory" in _table_names(conn):
            conn.execute(
                "UPDATE inventory "
                + "SET item = REPLACE(item, 'frog:leaf_frog:', "
                + "'frog:basic:') "
                + "WHERE item LIKE 'frog:leaf_frog:%'"
            )
        if "member_frog_log" in _table_names(conn):
            conn.execute(MEMBER_FROG_LOG_DDL)
            conn.execute(
                """
                INSERT INTO member_frog_log_new (id, uid, type, at, waited_for)
                SELECT id, uid,
                       CASE WHEN type = 'leaf_frog' THEN 'basic' ELSE type END,
                       at, waited_for
                FROM member_frog_log
                """
            )
            conn.execute("DROP TABLE member_frog_log")
            conn.execute(
                "ALTER TABLE member_frog_log_new RENAME TO member_frog_log"
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


MIGRATION = Migration(
    id="005_frog_species_key",
    doc="re-key frog stacks/log types from 'leaf_frog' to 'basic'",
    needs=needs_renaming,
    plan=plan,
    summary=lambda p: (
        f"re-key {p.inventory_rows} inventory row(s) and rewrite "
        f"{p.log_rows} log row(s)"
    ),
    migrate=migrate,
)
