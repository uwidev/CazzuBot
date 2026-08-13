"""One-off migration: add the poll message channel (``cid``) column.

The ``poll`` table gains ``cid`` — the channel hosting the poll's message
— so open/close can add/remove the vote button on that message. Existing
poll rows keep ``cid`` NULL (their buttons can only be edited after the
poll is re-sent). The column is appended last so the on-disk column order
matches the plugin's CREATE TABLE exactly (the boot-time schema guard
compares column order).

Run this while the bot is stopped, BEFORE booting the new code (the boot
time schema guard refuses to start on the legacy shape). Defaults to a
dry run; pass ``--commit`` to write. The original database is backed up
to ``data/poll_cid_backup-<timestamp>.db`` before any mutation.
"""

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_log = logging.getLogger("migrate_poll_cid")


def _has_cid(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA table_info(poll)").fetchall()
    return any(row[1] == "cid" for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default="data/cazzubot-prod.db", help="sqlite database file"
    )
    parser.add_argument(
        "--backup-dir",
        default="data",
        help="where to write the pre-migration backup (default data/)",
    )
    parser.add_argument(
        "--commit", action="store_true", help="apply the change (dry-run by default)"
    )
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "poll" not in tables:
            print(f"{args.db}: no poll table — nothing to migrate")
            return 0
        if _has_cid(conn):
            print(f"{args.db}: poll.cid already present — nothing to do")
            return 0

        count = conn.execute("SELECT COUNT(*) FROM poll").fetchone()[0]
        print(f"{args.db}: would add poll.cid ({count} existing poll row(s))")
        if not args.commit:
            print("dry run — pass --commit to apply")
            return 0

        backup = (
            Path(args.backup_dir)
            / f"poll_cid_backup-{time.strftime('%Y%m%d-%H%M%S')}.db"
        )
        backup.parent.mkdir(parents=True, exist_ok=True)
        src = sqlite3.connect(args.db)
        dst = sqlite3.connect(backup)
        src.backup(dst)
        dst.close()
        src.close()
        print(f"backed up to {backup}")

        conn.execute("ALTER TABLE poll ADD COLUMN cid INTEGER")
        conn.commit()
        assert _has_cid(conn), "ALTER TABLE did not add cid"
        print("poll.cid added")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
