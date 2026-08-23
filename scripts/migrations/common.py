"""Shared harness for the in-place SQLite migrations.

Every migration in ``scripts/migrations/`` is one :class:`Migration` with
the same shape the one-off scripts (``migrate_poll_cid``,
``migrate_counter_events``, ...) converged on:

- ``needs(conn)`` — idempotence gate: True only while the legacy shape (or
  stale values) is present, so re-running is a no-op and a fresh DB is
  skipped.
- ``plan(conn)`` — read-only report of what the write would do.
- ``migrate(conn)`` — the write; owns its own ``BEGIN``/``COMMIT`` and
  rolls back on any error.
- ``verify(conn)`` (optional) — post-commit checks beyond the ``needs()``
  gate.

The runner CLI (``scripts/migrate.py``) and the thin per-migration wrapper
scripts share the original one-off conventions: dry run by default,
``--commit`` to write, backup before any mutation, run while the bot is
stopped (the boot-time schema guard refuses to start on a legacy shape).

Call graph: ``run_one`` is the single apply path — used by both
``scripts/migrate.py`` (all pending migrations) and the per-script
wrappers (one migration); ``wrapper_main`` is the wrapper CLI entry.
"""

import argparse
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# -- model ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Migration:
    """One stateful (data) migration, applied in ``MIGRATIONS`` order.

    ``id`` is the stable identity (also used as the backup tag, e.g.
    ``001_poll_cid_backup-<timestamp>.db``); ``summary`` turns the
    ``plan``/``migrate`` report into one printable line.
    """

    id: str
    doc: (
        str  # one-line description, shown by ``scripts/migrate.py --list``
    )
    needs: Callable[[sqlite3.Connection], bool]
    plan: Callable[[sqlite3.Connection], Any]
    summary: Callable[[Any], str]
    migrate: Callable[[sqlite3.Connection], Any]
    verify: Callable[[sqlite3.Connection], None] | None = None


# -- helpers ---------------------------------------------------------------


def backup(db_path: Path, backup_dir: str, tag: str) -> Path:
    """Consistent point-in-time copy of the database before mutation."""
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = Path(backup_dir) / f"{tag}_backup-{stamp}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def run_one(
    migration: Migration,
    conn: sqlite3.Connection,
    *,
    commit: bool,
    backup_dir: str,
    db_path: Path,
) -> int:
    """Plan (dry run) or apply one migration against ``conn``.

    Idempotent: skips when ``needs()`` is False. On the commit path the
    database is backed up first, ``migrate()`` runs (it owns its own
    transaction), and the ``needs()`` gate plus optional ``verify()`` are
    re-checked before reporting success.
    """
    if not migration.needs(conn):
        print(
            f"{migration.id}: already applied (or never needed) — "
            + "nothing to do"
        )
        return 0

    report = migration.plan(conn)
    print(f"{migration.id}: {migration.summary(report)}")
    if not commit:
        print("dry run — pass --commit to apply")
        return 0

    saved = backup(db_path, backup_dir, migration.id)
    print(f"backed up to {saved}")

    did = migration.migrate(conn)
    assert not migration.needs(conn), "migration did not complete"
    if migration.verify is not None:
        migration.verify(conn)
    print(f"{migration.id}: applied — {migration.summary(did)}")
    return 0


def wrapper_main(migration: Migration, doc: str | None = None) -> int:
    """CLI entry for the thin per-migration wrapper scripts.

    Keeps the original ``--db`` / ``--backup-dir`` / ``--commit`` contract
    so old invocations keep working while delegating to the shared harness.
    ``doc`` defaults to the migration's one-liner.
    """
    parser = argparse.ArgumentParser(description=doc or migration.doc)
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
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        return run_one(
            migration,
            conn,
            commit=args.commit,
            backup_dir=args.backup_dir,
            db_path=Path(args.db),
        )
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit("this is a library module; run scripts/migrate.py instead")
