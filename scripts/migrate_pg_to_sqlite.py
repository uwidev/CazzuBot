#!/bin/env python
"""One-off PostgreSQL -> SQLite migration for CazzuBot v2.

Reads the live v1 PostgreSQL database (read-only), transforms every table per
``scripts/migration/MAPPING.md``, and writes a fresh v2 SQLite database whose
schema is imported from the real v2 DDL lists (settings, scheduler, plugins).

Usage::

    PGPASSWORD=... uv run --group migration python scripts/migrate_pg_to_sqlite.py
                           [--gid 293796316193095690] [--out data/cazzubot.migrated.db]

Defaults: host 192.168.1.3, port 5432, db main, user cazzubot, no SSL,
gid from GUILD_ID in .env. Never writes to the source; never touches the
live dev database (writes to a fresh file only).
"""

import argparse
import asyncio
import json
import logging
import os
import sqlite3
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

# make the project root importable when run as ``python scripts/<name>.py``
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
from dotenv import load_dotenv

# -- schema: import the real v2 DDL lists ----------------------------------
from cazzubot.db import dump_json
from cazzubot.scheduler import SCHEMA as _TASKS_SCHEMA
from cazzubot.settings import SCHEMA as _SETTINGS_SCHEMA
from plugins.counter.db import SCHEMA as _COUNTER_SCHEMA
from plugins.experience.db import SCHEMA as _EXP_SCHEMA
from plugins.frogs.db import SCHEMA as _FROGS_SCHEMA
from plugins.mod.db import SCHEMA as _MOD_SCHEMA
from plugins.poll.db import SCHEMA as _POLL_SCHEMA
from plugins.ranks.db import SCHEMA as _RANKS_SCHEMA

_log = logging.getLogger("migrate_pg_to_sqlite")

#: sentinel timestamp for exp-log rows whose v1 ``at`` is NULL (see MAPPING.md)
SENTINEL_AT = "1970-01-01T00:00:00+00:00"

SCHEMA_SOURCES = [
    _SETTINGS_SCHEMA,
    _TASKS_SCHEMA,
    _EXP_SCHEMA,
    _FROGS_SCHEMA,
    _RANKS_SCHEMA,
    _MOD_SCHEMA,
    _POLL_SCHEMA,
    _COUNTER_SCHEMA,
]

ARCHIVE_DDL = """
CREATE TABLE IF NOT EXISTS _archive_member_frog_deprecated_normal (
	uid               INTEGER PRIMARY KEY,
	deprecated_normal INTEGER NOT NULL
)
"""


# -- transforms -------------------------------------------------------------

#: asyncpg returns untyped Record mappings; transforms read named columns.
RowTransform = Callable[[dict[str, Any]], tuple[Any, ...]]
#: (sqlite table, select, count-sql, insert, transform)
TableSpec = tuple[str, str, str, str, RowTransform]


def iso(value: Any) -> str | None:
    """datetime | None -> ISO-8601 string | None."""
    return value.isoformat() if value is not None else None


def to0(value: Any) -> Any:
    """None -> 0 (v2 columns are NOT NULL DEFAULT 0)."""
    return 0 if value is None else value


def to_flag(value: Any) -> int:
    """bool -> 1/0 for v2 integer flags."""
    return 1 if value else 0


def exp_row(r: dict[str, Any]) -> tuple[Any, ...]:
    """Project a PG exp-log row into a SQLite tuple."""
    return (r["uid"], r["exp"], iso(r["at"]) or SENTINEL_AT, r["source"])


def exp_stats_row(r: dict[str, Any]) -> tuple[Any, ...]:
    """Project a PG member-exp row into a SQLite tuple."""
    return (r["uid"], r["lifetime"], r["msg_cnt"], iso(r["cdr"]))


def frog_row(r: dict[str, Any]) -> tuple[Any, ...]:
    """Project a PG member-frog row into a SQLite tuple."""
    return (
        r["uid"],
        to0(r["normal"]),
        to0(r["frozen"]),
        to0(r["capture"]),
    )


def frog_log_row(r: dict[str, Any]) -> tuple[Any, ...]:
    """Project a PG frog-log row into a SQLite tuple."""
    return (
        r["uid"],
        r["type"],
        iso(r["at"]) or SENTINEL_AT,
        r["waited_for"],
    )


def spawn_row(r: dict[str, Any]) -> tuple[Any, ...]:
    """Project a PG frog-spawn row into a SQLite tuple."""
    return (r["cid"], r["interval"], r["persist"], r["fuzzy"])


def threshold_row(r: dict[str, Any]) -> tuple[Any, ...]:
    """Project a PG rank-threshold row into a SQLite tuple."""
    return (r["rid"], to0(r["threshold"]), r["mode"])


def modlog_row(r: dict[str, Any]) -> tuple[Any, ...]:
    """Project a PG modlog row into a SQLite tuple."""
    return (
        r["case_id"],
        r["uid"],
        r["log_type"],
        iso(r["given_on"]),
        r["status"],
        iso(r["expires_on"]),
        r["reason"],
    )


def poll_row(r: dict[str, Any]) -> tuple[Any, ...]:
    """Project a PG poll row into a SQLite tuple."""
    return (
        r["id"],
        r["title"],
        r["description"] or "",
        r["max_vote"],
        r["mid"],
        to_flag(r["open"]),
    )


# (sqlite table, select, count-sql, insert, transform)
TABLES: list[TableSpec] = [
    (
        "member_exp",
        "SELECT uid, lifetime, msg_cnt, cdr FROM member_exp WHERE gid = $1",
        "SELECT COUNT(*) FROM member_exp WHERE gid = $1",
        "INSERT INTO member_exp (uid, lifetime, msg_cnt, cdr) VALUES (?, ?, ?, ?)",
        exp_stats_row,
    ),
    (
        "member_exp_log",
        "SELECT uid, exp, at, source FROM member_exp_log WHERE gid = $1",
        "SELECT COUNT(*) FROM member_exp_log WHERE gid = $1",
        "INSERT INTO member_exp_log (uid, exp, at, source) VALUES (?, ?, ?, ?)",
        exp_row,
    ),
    (
        "member_frog",
        "SELECT uid, normal, frozen, capture FROM member_frog WHERE gid = $1",
        "SELECT COUNT(*) FROM member_frog WHERE gid = $1",
        "INSERT INTO member_frog (uid, normal, frozen, capture) VALUES (?, ?, ?, ?)",
        frog_row,
    ),
    (
        "member_frog_log",
        "SELECT uid, type, at, waited_for FROM member_frog_log "
        + "WHERE gid = $1 OR gid IS NULL",
        "SELECT COUNT(*) FROM member_frog_log WHERE gid = $1 OR gid IS NULL",
        "INSERT INTO member_frog_log (uid, type, at, waited_for) VALUES (?, ?, ?, ?)",
        frog_log_row,
    ),
    (
        "frog_spawn",
        "SELECT cid, interval, persist, fuzzy FROM frog_spawn WHERE gid = $1",
        "SELECT COUNT(*) FROM frog_spawn WHERE gid = $1",
        "INSERT INTO frog_spawn (cid, interval, persist, fuzzy) VALUES (?, ?, ?, ?)",
        spawn_row,
    ),
    (
        "rank_threshold",
        "SELECT rid, threshold, mode FROM rank_threshold WHERE gid = $1",
        "SELECT COUNT(*) FROM rank_threshold WHERE gid = $1",
        "INSERT INTO rank_threshold (rid, threshold, mode) VALUES (?, ?, ?)",
        threshold_row,
    ),
    (
        "modlog",
        "SELECT uid, case_id, log_type, given_on, status, expires_on, reason "
        + "FROM modlog WHERE gid = $1",
        "SELECT COUNT(*) FROM modlog WHERE gid = $1",
        "INSERT INTO modlog (id, uid, log_type, given_on, status, expires_on, reason) "
        + "VALUES (?, ?, ?, ?, ?, ?, ?)",
        modlog_row,
    ),
    (
        "poll",
        "SELECT id, title, description, max_vote, mid, open FROM poll WHERE gid = $1",
        "SELECT COUNT(*) FROM poll WHERE gid = $1",
        "INSERT INTO poll (id, title, description, max_vote, mid, open) "
        + "VALUES (?, ?, ?, ?, ?, ?)",
        poll_row,
    ),
]


async def migrate_table(
    pg: Any, sqlite: sqlite3.Connection, gid: int, spec: TableSpec
) -> dict[str, Any]:
    """Stream rows from postgres, transform, batch-insert into sqlite."""
    name, select, count_sql, insert_sql, transform = spec
    src_count = await pg.fetchval(count_sql, gid)
    inserted = 0
    cur = await pg.cursor(select, gid)
    while True:
        records = await cur.fetch(20_000)
        if not records:
            break
        sqlite.executemany(insert_sql, [transform(r) for r in records])
        sqlite.commit()
        inserted += len(records)
    return {"table": name, "source": src_count, "inserted": inserted}


async def migrate_counters(
    pg: Any, sqlite: sqlite3.Connection, gid: int
) -> list[dict[str, Any]]:
    """Migrate v1 counters into the event-based v2 shape.

    Each v1 row ``(mid, count)`` becomes one ``counter`` registry row plus
    ``count`` anonymous ``counter_event`` rows (``uid``/``name`` NULL, epoch
    timestamp) so the derived total carries over exactly. ``counter_baka``
    does not exist in v1 (the footer history was embed-only), so nothing
    else is ported.
    """
    rows = await pg.fetch(
        "SELECT mid, count FROM counter WHERE gid = $1 ORDER BY mid", gid
    )
    counters = 0
    events = 0
    batch: list[tuple[int, str]] = []
    for r in rows:
        cur = sqlite.execute(
            "INSERT INTO counter (mid) VALUES (?)", (r["mid"],)
        )
        counter_id = cur.lastrowid
        assert counter_id is not None  # AUTOINCREMENT always assigns an id
        counters += 1
        events += r["count"]
        batch.extend((counter_id, SENTINEL_AT) for _ in range(r["count"]))
    sqlite.executemany(
        "INSERT INTO counter_event (counter_id, uid, name, updated_at)"
        + " VALUES (?, NULL, NULL, ?)",
        batch,
    )
    sqlite.commit()
    return [
        {"table": "counter", "source": len(rows), "inserted": counters},
        {
            "table": "counter_event",
            "source": sum(r["count"] for r in rows),
            "inserted": events,
        },
    ]


async def migrate_polls(
    pg: Any, sqlite: sqlite3.Connection, gid: int
) -> list[dict[str, Any]]:
    """Migrate poll items + votes, renumbering per-poll item ids.

    v1 ``poll_item.id`` is unique only per (gid, pid); v2 requires globally
    unique item ids (``poll_vote.iid`` references them by a single column).
    Assign new global ids in (pid, id) order and rewrite vote ``iid``s.
    """
    report: list[dict[str, Any]] = []

    items = await pg.fetch(
        "SELECT id, pid FROM poll_item WHERE gid = $1 ORDER BY pid, id",
        gid,
    )
    mapping: dict[tuple[int, int], int] = {}
    rows: list[tuple[int, Any]] = []
    for new_id, item in enumerate(items, start=1):
        mapping[(item["pid"], item["id"])] = new_id
        rows.append((new_id, item["pid"]))
    sqlite.executemany(
        "INSERT INTO poll_item (id, pid) VALUES (?, ?)", rows
    )
    sqlite.commit()
    report.append(
        {"table": "poll_item", "source": len(items), "inserted": len(rows)}
    )

    votes = await pg.fetch(
        "SELECT pid, iid, uid, count FROM poll_vote WHERE gid = $1", gid
    )
    inserted = skipped = 0
    batch: list[tuple[Any, ...]] = []
    for v in votes:
        new_iid = mapping.get((v["pid"], v["iid"]))
        if new_iid is None:
            skipped += 1
            continue
        batch.append((v["pid"], new_iid, v["uid"], v["count"]))
        inserted += 1
    sqlite.executemany(
        "INSERT INTO poll_vote (pid, iid, uid, count) VALUES (?, ?, ?, ?)",
        batch,
    )
    sqlite.commit()
    report.append(
        {
            "table": "poll_vote",
            "source": len(votes),
            "inserted": inserted,
            "skipped": skipped,
        }
    )
    return report


async def migrate_settings(
    pg: Any, sqlite: sqlite3.Connection, gid: int
) -> list[tuple[str, bool]]:
    """Port v1 config tables into v2 ``settings`` rows (JSON-encoded)."""
    report: list[tuple[str, bool]] = []

    def put(key: str, value: Any) -> bool:
        if value is None:
            return False
        sqlite.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            + "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, dump_json(value)),
        )
        return True

    # guild -> inktober.cid
    row = await pg.fetchrow("SELECT * FROM guild WHERE gid = $1", gid)
    if row:
        report.append(
            (
                "guild.inktober_cid",
                put("inktober.cid", row["inktober_cid"]),
            )
        )

    # level -> level.message / level.quiet
    row = await pg.fetchrow("SELECT * FROM level WHERE gid = $1", gid)
    if row:
        report.append(
            (
                "level.message",
                put("level.message", json.loads(row["message"])),
            )
        )
        report.append(
            ("level.quiet", put("level.quiet", list(row["quiet"] or [])))
        )

    # rank -> rank.{mode}.{message,enabled,keep_old}
    for row in await pg.fetch("SELECT * FROM rank WHERE gid = $1", gid):
        mode = row["mode"]
        report.append(
            (
                f"rank.{mode}.message",
                put(f"rank.{mode}.message", json.loads(row["message"])),
            )
        )
        report.append(
            (
                f"rank.{mode}.enabled",
                put(f"rank.{mode}.enabled", row["enabled"]),
            )
        )
        report.append(
            (
                f"rank.{mode}.keep_old",
                put(f"rank.{mode}.keep_old", row["keep_old"]),
            )
        )

    # frog -> frog.message / frog.enabled
    row = await pg.fetchrow("SELECT * FROM frog WHERE gid = $1", gid)
    if row:
        report.append(
            (
                "frog.message",
                put("frog.message", json.loads(row["message"])),
            )
        )
        report.append(
            ("frog.enabled", put("frog.enabled", row["enabled"]))
        )

    # welcome -> welcome.*
    row = await pg.fetchrow("SELECT * FROM welcome WHERE gid = $1", gid)
    if row:
        for key, col in (
            ("welcome.enabled", "enabled"),
            ("welcome.default_rid", "default_rid"),
            ("welcome.cid", "cid"),
            ("welcome.message", "message"),
            ("welcome.mode", "mode"),
            ("welcome.monitor_rid", "monitor_rid"),
        ):
            value = row[col]
            if key == "welcome.message" and value is not None:
                value = json.loads(value)
            report.append((key, put(key, value)))

    # internal -> daily.last_daily / quarterly.last_quarterly
    for row in await pg.fetch("SELECT * FROM internal"):
        key = {
            "last_daily": "daily.last_daily",
            "last_quarterly": "quarterly.last_quarterly",
        }.get(row["field"])
        if key:
            report.append(
                (f"internal.{row['field']}", put(key, row["value"]))
            )

    sqlite.commit()
    return report


async def migrate_archive(
    pg: Any, sqlite: sqlite3.Connection, gid: int
) -> int:
    """Archive v1 ``member_frog.deprecated_normal`` (see MAPPING.md)."""
    sqlite.execute(ARCHIVE_DDL)
    rows = await pg.fetch(
        "SELECT uid, deprecated_normal FROM member_frog "
        + "WHERE gid = $1 AND deprecated_normal <> 0",
        gid,
    )
    sqlite.executemany(
        "INSERT INTO _archive_member_frog_deprecated_normal (uid, deprecated_normal) "
        + "VALUES (?, ?)",
        [(r["uid"], r["deprecated_normal"]) for r in rows],
    )
    sqlite.commit()
    return len(rows)


def verify_sqlite(sqlite: sqlite3.Connection, _gid: int) -> list[str]:
    """Post-load sanity checks; returns a list of problem strings (empty = ok)."""
    problems: list[str] = []

    for (table,) in sqlite.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ):
        n = sqlite.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        _log.info("sqlite %-40s %8d rows", table, n)

    # lifetime must equal the sum of log exp per uid (sentinel guarantees it)
    mismatch = sqlite.execute(
        """
		SELECT COUNT(*) FROM member_exp e
		LEFT JOIN (SELECT uid, SUM(exp) AS s FROM member_exp_log GROUP BY uid) l
			ON l.uid = e.uid
		WHERE e.lifetime <> COALESCE(l.s, 0)
		"""
    ).fetchone()[0]
    if mismatch:
        problems.append(
            f"{mismatch} member_exp rows where lifetime != SUM(exp_log)"
        )

    # capture vs frog-log counts: informational only (lifetime counter vs logs)
    diff = sqlite.execute(
        """
		SELECT COUNT(*) FROM member_frog f
		LEFT JOIN (SELECT uid, COUNT(*) AS n FROM member_frog_log GROUP BY uid) l
			ON l.uid = f.uid
		WHERE f.capture <> COALESCE(l.n, 0)
		"""
    ).fetchone()[0]
    _log.info(
        "capture != frog_log count for %d members (expected; informational)",
        diff,
    )

    # polls with items but no votes / votes referencing missing items
    orphan_votes = sqlite.execute(
        """
		SELECT COUNT(*) FROM poll_vote v
		WHERE NOT EXISTS (SELECT 1 FROM poll_item i WHERE i.id = v.iid)
		"""
    ).fetchone()[0]
    if orphan_votes:
        problems.append(
            f"{orphan_votes} poll_votes reference missing poll_items"
        )

    return problems


async def main() -> int:
    """Migrate the PostgreSQL database into SQLite (CLI entry)."""
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host", default=os.getenv("PGHOST", "192.168.1.3")
    )
    parser.add_argument(
        "--port", type=int, default=int(os.getenv("PGPORT", "5432"))
    )
    parser.add_argument("--db", default=os.getenv("PGDATABASE", "main"))
    parser.add_argument("--user", default=os.getenv("PGUSER", "cazzubot"))
    parser.add_argument(
        "--gid",
        type=int,
        default=int(os.getenv("GUILD_ID", "0")),
        help="target guild id (default: GUILD_ID from .env)",
    )
    parser.add_argument(
        "--out",
        default="data/cazzubot.migrated.db",
        help="output sqlite path",
    )
    args = parser.parse_args()

    password = os.getenv("PGPASSWORD")
    if not password:
        _log.error("PGPASSWORD env var is required")
        return 2
    if not args.gid:
        _log.error("--gid required (or GUILD_ID in .env)")
        return 2

    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(message)s"
    )

    # asyncpg is untyped (no py.typed); the cast is the boundary to Any.
    pg = cast(
        Any,
        await asyncpg.connect(
            host=args.host,
            port=args.port,
            user=args.user,
            password=password,
            database=args.db,
            ssl=False,
            timeout=15,
        ),
    )
    _log.info(
        "connected to postgres %s:%s/%s", args.host, args.port, args.db
    )

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    sqlite = sqlite3.connect(out)
    sqlite.execute("PRAGMA journal_mode=WAL")
    sqlite.execute("PRAGMA synchronous=OFF")
    for statements in SCHEMA_SOURCES:
        for stmt in statements:
            sqlite.execute(stmt)
    sqlite.execute(ARCHIVE_DDL)
    sqlite.commit()
    _log.info("schema applied from %d DDL sources", len(SCHEMA_SOURCES))

    report: list[dict[str, Any]] = []
    try:
        # asyncpg cursors need a transaction; SELECT-only, never mutates source
        async with pg.transaction():
            for spec in TABLES:
                info = await migrate_table(pg, sqlite, args.gid, spec)
                report.append(info)
                status = (
                    "OK"
                    if info["source"] == info["inserted"]
                    else "MISMATCH"
                )
                _log.info(
                    "%-16s source=%9d inserted=%9d %s",
                    info["table"],
                    info["source"],
                    info["inserted"],
                    status,
                )

            for info in await migrate_polls(pg, sqlite, args.gid):
                status = (
                    "OK"
                    if info["source"] == info["inserted"]
                    else "MISMATCH"
                )
                _log.info(
                    "%-16s source=%9d inserted=%9d %s",
                    info["table"],
                    info["source"],
                    info["inserted"],
                    status,
                )

            for info in await migrate_counters(pg, sqlite, args.gid):
                status = (
                    "OK"
                    if info["source"] == info["inserted"]
                    else "MISMATCH"
                )
                _log.info(
                    "%-16s source=%9d inserted=%9d %s",
                    info["table"],
                    info["source"],
                    info["inserted"],
                    status,
                )

            archived = await migrate_archive(pg, sqlite, args.gid)
            _log.info(
                "archived deprecated_normal for %d members", archived
            )

            for key, stored in await migrate_settings(
                pg, sqlite, args.gid
            ):
                _log.info(
                    "settings %-32s %s",
                    key,
                    "stored" if stored else "skipped (NULL)",
                )

            # special-case counters for the report
            null_at = await pg.fetchval(
                "SELECT COUNT(*) FROM member_exp_log "
                + "WHERE gid = $1 AND at IS NULL",
                args.gid,
            )
            null_gid_logs = await pg.fetchval(
                "SELECT COUNT(*) FROM member_frog_log WHERE gid IS NULL"
            )
            frozen_src = await pg.fetchval(
                "SELECT COUNT(*) FROM member_exp_log "
                + "WHERE gid = $1 AND source = 'frozen'",
                args.gid,
            )
            _log.info(
                "special: exp_log rows with NULL at (sentineled): %d",
                null_at,
            )
            _log.info(
                "special: frog_log rows with NULL gid (attributed): %d",
                null_gid_logs,
            )
            _log.info(
                "special: exp_log rows with source 'frozen' (kept): %d",
                frozen_src,
            )

        problems = verify_sqlite(sqlite, args.gid)
        _log.info(
            "tasks table left empty (v2 re-schedules spawns at boot)"
        )
        _log.info("out: %s", out)
        if problems:
            for p in problems:
                _log.error("VERIFY FAIL: %s", p)
            return 1
        _log.info("all post-load verification checks passed")
        return 0
    finally:
        sqlite.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        sqlite.close()
        await pg.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
