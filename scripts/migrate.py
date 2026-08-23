#!/bin/env python
"""Run the in-place SQLite migrations through the shared harness.

Discovers the explicit ``MIGRATIONS`` registry in ``scripts/migrations/``
and applies every pending migration in order. Conventions inherited from
the original one-off scripts:

- Dry run by default; pass ``--commit`` to write.
- Each database is backed up to
  ``<backup-dir>/<migration-id>_backup-<timestamp>.db`` before its
  mutation.
- Run this while the bot is stopped: the boot-time schema guard refuses to
  start on a legacy shape, and these migrations target the live file.

Usage::

    python scripts/migrate.py [--db data/cazzubot-dev.db] [--commit]
    python scripts/migrate.py --list
    python scripts/migrate.py --only 003_frog_species --commit

The per-migration wrapper scripts (``scripts/migrate_frog_species.py``,
...) keep the old invocation working and delegate here via
``scripts/migrations/common.py``'s ``wrapper_main``.
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.migrations import MIGRATIONS  # noqa: E402
from scripts.migrations.common import run_one  # noqa: E402


def main() -> int:
    """Apply pending migrations (CLI entry)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default="data/cazzubot-prod.db",
        help="sqlite database file",
    )
    parser.add_argument(
        "--backup-dir",
        default="data",
        help="where to write pre-migration backups (default data/)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="apply changes (dry-run by default)",
    )
    parser.add_argument(
        "--only",
        default=None,
        help="migration id (or substring) to run instead of all pending",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list migrations and their state, then exit",
    )
    args = parser.parse_args()

    selected = [
        m for m in MIGRATIONS if args.only is None or args.only in m.id
    ]
    if not selected:
        print(f"no migrations match --only {args.only!r}")
        return 1

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        if args.list:
            for m in MIGRATIONS:
                state = (
                    "pending"
                    if m.needs(conn)
                    else "ok (applied or never needed)"
                )
                print(f"  {m.id:24} {state:32} {m.doc}")
            return 0

        pending = [m for m in selected if m.needs(conn)]
        if not pending:
            print(f"{args.db}: no pending migrations — all up to date")
            return 0

        for m in pending:
            run_one(
                m,
                conn,
                commit=args.commit,
                backup_dir=args.backup_dir,
                db_path=Path(args.db),
            )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
