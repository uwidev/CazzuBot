"""One-off migration: species inventory replaces ``member_frog.normal/frozen``.

The legacy shape stores frog quantities as columns on ``member_frog``
(``normal``/``frozen``) and records captures in ``member_frog_log.type``
as ``'normal'``/``'frozen'``. The new shape keeps quantities in the
generic inventory (``cazzubot/inventory.py`` — frog stacks as
``frog:<species>:<state>`` items) and stores the species key in
``member_frog_log.type``. Species themselves are code-defined
(``plugins/frogs/species.py``), so no species rows are created — the
legacy quantities fold into the default species' (``leaf_frog``)
inventory.

Run this while the bot is stopped, BEFORE booting the new code (the
boot-time schema guard refuses the legacy shape). Defaults to a dry run;
pass ``--commit`` to write. The original database is backed up to
``data/frog_species_backup-<timestamp>.db`` before any mutation.
Idempotent: skips when the legacy shape is absent.

Call graph (per the self-documenting rule): ``main()`` is the CLI entry
(``python scripts/migrate_frog_species.py``); it uses ``plan`` for the
dry-run report and ``migrate`` for the write. Tests drive ``plan`` /
``migrate`` / ``needs_migration`` directly against a temp legacy DB.
"""

import argparse
import logging
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_log = logging.getLogger("migrate_frog_species")

# mirrors plugins/frogs/species.py SpeciesKey.LEAF_FROG.value
DEFAULT_SPECIES_KEY = "leaf_frog"

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
    type       TEXT NOT NULL DEFAULT 'leaf_frog',
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
        "WHERE type IN ('normal', 'frozen')"
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


def main() -> int:
    """Migrate frog species columns (CLI entry)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default="data/cazzubot-prod.db",
        help="sqlite database file",
    )
    parser.add_argument(
        "--backup-dir",
        default="data",
        help="where to write the pre-migration backup (default data/)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="apply the change (dry-run by default)",
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        if not needs_migration(conn):
            print(
                f"{args.db}: no legacy frog shape (already migrated or "
                "absent) — nothing to do"
            )
            return 0

        report = plan(conn)
        print(
            f"{args.db}: would move {report.members} member(s), "
            f"insert {report.inventory_rows} inventory row(s), "
            f"rewrite {report.log_rows} log row(s)"
        )
        if not args.commit:
            print("dry run — pass --commit to apply")
            return 0

        backup = (
            Path(args.backup_dir)
            / f"frog_species_backup-{time.strftime('%Y%m%d-%H%M%S')}.db"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(args.db)
        dst = sqlite3.connect(backup)
        src.backup(dst)
        dst.close()
        src.close()
        print(f"backed up to {backup}")

        did = migrate(conn)
        assert not needs_migration(conn), "migration did not complete"
        print(
            f"migrated: {did.members} member(s), {did.inventory_rows} "
            f"inventory row(s), {did.log_rows} log row(s) rewritten"
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
