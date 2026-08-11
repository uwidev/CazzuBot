"""One-off migration: legacy counter tables -> event-based counter tables.

Converts a pre-event counter DB — ``counter(mid, count)`` plus
``counter_baka(mid, uid, name, updated_at)`` — into the v2 shape the
``counter`` plugin now expects:

- ``counter(id, mid)`` — registry with a unique id, no stored count
- ``counter_event(id, counter_id, uid, name, updated_at)`` — one row per
  press, ``counter_id`` fkeying to ``counter.id``

Existing per-user ``counter_baka`` rows carry over as real events (their
``uid``/``name``/``updated_at`` are preserved); the remaining aggregate
``count`` is backfilled as anonymous rows (``uid``/``name`` NULL, epoch
``updated_at`` ``1970-01-01T00:00:00+00:00``) so the derived total matches
the old stored count exactly.

Run this while the bot is stopped, BEFORE booting the new code (the boot
time schema guard refuses to start on the legacy shape). Defaults to a
dry run; pass ``--commit`` to write. The original database is backed up to
``data/counter_events_backup-<timestamp>.db`` before any mutation.
"""

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

# make the project root importable when run as ``python scripts/<name>.py``
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plugins.counter.db import SCHEMA as _COUNTER_SCHEMA

_log = logging.getLogger("migrate_counter_events")

EPOCH = "1970-01-01T00:00:00+00:00"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db", default="data/cazzubot.db", help="sqlite database file"
    )
    parser.add_argument(
        "--backup-dir",
        default="data",
        help="where to write the pre-migration backup (default data/)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="actually write; without it only the plan is printed",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    try:
        shape = _detect_shape(conn)
        if shape == "new":
            print(
                f"{db_path}: already event-based (counter_event exists) — "
                + "nothing to do"
            )
            return 0
        if shape == "legacy_mid_only":
            print(
                f"{db_path}: legacy mid-only counter table (no count column, "
                + "no counter_event) — nothing to migrate"
            )
            return 0

        rows = conn.execute("SELECT mid, count FROM counter ORDER BY mid")
        counters = [dict(r) for r in rows]
        baka = conn.execute(
            "SELECT mid, uid, name, updated_at FROM counter_baka"
        ).fetchall()
        by_mid: dict[int, list[dict[str, Any]]] = {}
        for r in baka:
            by_mid.setdefault(int(r["mid"]), []).append(dict(r))

        print(f"{db_path}: legacy counter tables found")
        total_events = 0
        for c in counters:
            real = len(by_mid.get(c["mid"], []))
            backfill = max(0, c["count"] - real)
            total_events += real + backfill
            print(
                f"  mid={c['mid']} count={c['count']} "
                + f"-> {real} real event(s) carried over, "
                + f"{backfill} anonymous backfilled, total events={real + backfill}"
            )
        print(
            f"  sum: {len(counters)} counter(s), {total_events} total events"
        )

        if not args.commit:
            print("\ndry run — pass --commit to migrate")
            return 0

        backup_path = _backup(db_path, args.backup_dir)
        print(f"backed up to {backup_path}")

        with conn:
            _migrate(conn, counters, by_mid)
        _verify(conn, counters)
        print("migration committed and verified")
        return 0
    finally:
        conn.close()


# -- helpers ---------------------------------------------------------------


def _detect_shape(conn: sqlite3.Connection) -> str:
    """'legacy' (count column, no counter_event), 'new', or 'legacy_mid_only'."""
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "counter_event" in tables:
        return "new"
    if "counter" not in tables:
        return "legacy_mid_only"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(counter)")}
    if "count" in cols:
        return "legacy"
    return "legacy_mid_only"


def _backup(db_path: Path, backup_dir: str) -> Path:
    """Consistent point-in-time copy of the database before mutation."""
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = Path(backup_dir) / f"counter_events_backup-{stamp}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def _migrate(
    conn: sqlite3.Connection,
    counters: list[dict[str, Any]],
    by_mid: dict[int, list[dict[str, Any]]],
) -> None:
    """Rebuild the tables inside the caller's transaction (``with conn:``)."""
    # keep the old table's data under a temp name, then recreate the new
    # shape from the plugin's own DDL so boot-time schema parity holds
    conn.execute("ALTER TABLE counter RENAME TO counter_legacy")
    for statement in _COUNTER_SCHEMA:
        conn.execute(statement)

    # registry rows first (the events fkey to counter.id); both lists are
    # ordered by mid so the ids line up with the legacy rows
    conn.executemany(
        "INSERT INTO counter (mid) VALUES (?)",
        [(c["mid"],) for c in counters],
    )
    new_ids = [
        int(r[0])
        for r in conn.execute(
            "SELECT id FROM counter ORDER BY mid"
        ).fetchall()
    ]
    if len(new_ids) != len(counters):
        raise RuntimeError(
            "counter registry rows do not match the legacy table"
        )

    rows: list[tuple[int, int | None, str | None, str]] = []
    for c, new_id in zip(counters, new_ids):
        real = by_mid.get(c["mid"], [])
        for r in real:
            rows.append((new_id, r["uid"], r["name"], r["updated_at"]))
        backfill = max(0, c["count"] - len(real))
        rows.extend((new_id, None, None, EPOCH) for _ in range(backfill))
    conn.executemany(
        "INSERT INTO counter_event (counter_id, uid, name, updated_at)"
        + " VALUES (?, ?, ?, ?)",
        rows,
    )

    conn.execute("DROP TABLE counter_legacy")
    conn.execute("DROP TABLE counter_baka")


def _verify(
    conn: sqlite3.Connection, counters: list[dict[str, Any]]
) -> None:
    """Every counter's derived event total must equal the old stored count."""
    rows = conn.execute(
        "SELECT c.mid, COUNT(e.id) AS n FROM counter c"
        + " LEFT JOIN counter_event e ON e.counter_id = c.id"
        + " GROUP BY c.id"
    ).fetchall()
    got = {int(r["mid"]): int(r["n"]) for r in rows}
    for c in counters:
        if got.get(c["mid"]) != c["count"]:
            raise RuntimeError(
                f"mid {c['mid']}: expected {c['count']} events, "
                + f"got {got.get(c['mid'])}"
            )


if __name__ == "__main__":
    sys.exit(main())
