"""Migration: species inventory replaces ``member_frog.normal/frozen``.

The legacy shape stores frog quantities as columns on ``member_frog``
(``normal``/``frozen``) and records captures in ``member_frog_log.type``
as ``'normal'``/``'frozen'``. The new shape keeps quantities in the
generic inventory (``cazzubot/inventory.py`` — frog stacks as
``frog:<species>:<state>`` items) and stores the species key in
``member_frog_log.type``. Species themselves are code-defined
(``plugins/frogs/species.py``), so no species rows are created — the
legacy quantities fold into the default species' (``basic``)
inventory.

Idempotent: ``needs_migration`` is False once the generic ``inventory``
table exists or ``member_frog`` no longer carries ``normal``/``frozen``.
Run through ``scripts/migrate.py`` (all pending) or the thin wrapper
``scripts/migrate_frog_species.py``; dry-run by default, ``--commit`` to
write, backup before mutation, bot stopped.

Call graph: ``MIGRATION`` registers this module with the shared harness;
tests drive ``needs_migration`` / ``plan`` / ``migrate`` directly against a
temp legacy DB and boot the bot on the result (schema guard acceptance).
"""

import sqlite3
from dataclasses import dataclass

from scripts.migrations.common import Migration

# mirrors plugins/frogs/species.py FrogItemKey.BASIC.value
DEFAULT_SPECIES_KEY = "basic"

# The generic inventory DDL, mirroring cazzubot/inventory.py exactly: the
# boot-time schema guard compares column order, defaults and the
# AUTOINCREMENT keyword, so migrated tables must match the Python DDL.
# Frog stacks live here as items derived from FrogItem.key
# (plugins/frogs/db.py): "frog:<species>:<state>".
INVENTORY_DDL = """
CREATE TABLE IF NOT EXISTS inventory (
    uid  INTEGER NOT NULL,
    item TEXT NOT NULL,
    qty  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (uid, item)
)
"""

# member_frog_log is REBUILT (not altered) because its ``type`` default
# changed from 'normal' to the species key — a plain row rewrite would
# leave the old default and fail the schema guard.
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
class MigrationPlan:
    """What the migration found — the dry-run report."""

    members: int  # member_frog rows holding a normal/frozen quantity
    inventory_rows: int  # inventory rows to insert
    log_rows: int  # member_frog_log rows to rewrite to the species key


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True when the legacy frog shape is present.

    Legacy = the generic ``inventory`` table missing AND ``member_frog``
    still carries the ``normal``/``frozen`` columns. The idempotence gate:
    after the migration (or on a fresh/new DB) this is False.
    """
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "inventory" in tables or "member_frog" not in tables:
        return False
    columns = {
        r[1] for r in conn.execute("PRAGMA table_info(member_frog)")
    }
    return "normal" in columns or "frozen" in columns


def plan(conn: sqlite3.Connection) -> MigrationPlan:
    """Read-only counts of what :func:`migrate` would do (the dry-run report)."""
    members = conn.execute(
        "SELECT COUNT(*) FROM member_frog WHERE normal > 0 OR frozen > 0"
    ).fetchone()[0]
    normal_rows = conn.execute(
        "SELECT COUNT(*) FROM member_frog WHERE normal > 0"
    ).fetchone()[0]
    frozen_rows = conn.execute(
        "SELECT COUNT(*) FROM member_frog WHERE frozen > 0"
    ).fetchone()[0]
    log_rows = conn.execute(
        "SELECT COUNT(*) FROM member_frog_log "
        + "WHERE type IN ('normal', 'frozen')"
    ).fetchone()[0]
    return MigrationPlan(
        members=members,
        inventory_rows=normal_rows + frozen_rows,
        log_rows=log_rows,
    )


def migrate(conn: sqlite3.Connection) -> MigrationPlan:
    """Apply the migration in one transaction; returns what it did.

    Steps: create the generic ``inventory``; fold ``member_frog.normal``/
    ``frozen`` into it as frog items under the default species (zero
    quantities skipped); rebuild ``member_frog_log`` with the new DDL
    (rewriting ``'normal'``/``'frozen'`` types to the species key during
    the copy); drop the legacy columns. Callers gate on
    :func:`needs_migration` — with the new shape present there is nothing
    to do.
    """
    before = plan(conn)
    conn.execute("BEGIN")
    try:
        conn.execute(INVENTORY_DDL)
        conn.execute(
            """
            INSERT INTO inventory (uid, item, qty)
            SELECT uid, ?, normal
            FROM member_frog
            WHERE normal > 0
            """,
            (f"frog:{DEFAULT_SPECIES_KEY}:normal",),
        )
        conn.execute(
            """
            INSERT INTO inventory (uid, item, qty)
            SELECT uid, ?, frozen
            FROM member_frog
            WHERE frozen > 0
            """,
            (f"frog:{DEFAULT_SPECIES_KEY}:frozen",),
        )
        conn.execute(MEMBER_FROG_LOG_DDL)
        conn.execute(
            """
            INSERT INTO member_frog_log_new (id, uid, type, at, waited_for)
            SELECT id, uid,
                   CASE WHEN type IN ('normal', 'frozen') THEN ? ELSE type END,
                   at, waited_for
            FROM member_frog_log
            """,
            (DEFAULT_SPECIES_KEY,),
        )
        conn.execute("DROP TABLE member_frog_log")
        conn.execute(
            "ALTER TABLE member_frog_log_new RENAME TO member_frog_log"
        )
        conn.execute("ALTER TABLE member_frog DROP COLUMN normal")
        conn.execute("ALTER TABLE member_frog DROP COLUMN frozen")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


MIGRATION = Migration(
    id="003_frog_species",
    doc=(
        "fold member_frog.normal/frozen quantities into the generic "
        "inventory"
    ),
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        f"move {p.members} member(s), insert {p.inventory_rows} "
        f"inventory row(s), rewrite {p.log_rows} log row(s)"
    ),
    migrate=migrate,
)
