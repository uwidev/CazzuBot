#!/bin/env python
"""DEPRECATED — reverse-migrates the pre-species frog columns (``member_frog.normal/frozen``); not updated for the species rework. ``scripts/migrate_frog_species.py`` supersedes the frog part of the v2 schema.

Reverse migration: fill the v1 PostgreSQL DB from the v2 SQLite file.

One-way rollback helper for the v1 -> v2 cutover. The v1 PostgreSQL
database is frozen while the v2 bot runs (it records into SQLite only), so
at rollback time it is missing everything the trial recorded. This script
carries the exp, frog, and counter data back — the only tables that need
to survive a rollback (explicit scope decision; everything else keeps its
cutover state on PostgreSQL, which is exactly the state v1 expects).

Tables ported::

    member_exp, member_exp_log, member_frog, member_frog_log, frog_spawn,
    counter

Strategy is replace-per-guild: v1 was not writing during the trial, so the
SQLite file is a superset of the guild's PostgreSQL rows. Deleting the
guild's rows and inserting the full SQLite contents is lossless for these
tables, idempotent (re-runnable), and needs no merge logic. FK-support rows
(``guild``, ``user``, ``channel``) are backfilled first so the v1 foreign
keys hold for members/channels that appeared during the trial.

Usage::

    PGPASSWORD=... uv run --group migration python scripts/sqlite_to_pg.py
                           [--gid 293796316193095690]
                           [--sqlite data/cazzubot-prod.db]

Defaults to a **dry run** that prints the plan and writes nothing. Pass
``--commit`` to write; everything runs inside one transaction, and the
post-write per-uid parity check runs *before* commit, so any mismatch
rolls the whole thing back.

Timestamps are ISO-8601 UTC strings in SQLite. The historical bulk-import
rows (sentinel ``1970-01-01T00:00:00+00:00``) are written back as NULL,
which is exactly how v1 stored them; ``member_frog.deprecated_normal`` is
restored from the forward migration's archive table.

If the SQLite ``counter`` table predates the count column (legacy mid-only
shape), only counter *presence* is ported — existing v1 counts are never
touched and trial-created mids are registered with the v1 default (0). On
the event-based shape (``counter_event`` exists) the aggregate count is
derived from the press history instead of a stored column.

Run after stopping the v2 bot (the SQLite read is safe alongside a live
bot via WAL, but a quiescent file makes the snapshot unambiguous).
"""

import argparse
import asyncio
import logging
import os
import sqlite3
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, NamedTuple, cast

# make the project root importable when run as ``python scripts/<name>.py``
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
import pendulum
from dotenv import load_dotenv

_log = logging.getLogger("sqlite_to_pg")

#: sentinel timestamp for exp-log rows whose v1 ``at`` was NULL (MAPPING.md)
SENTINEL_AT = "1970-01-01T00:00:00+00:00"

BATCH = 20_000


class Table(NamedTuple):
    """One reverse-mapped table: pg write spec + sqlite source query."""

    name: str
    delete: str
    insert: str
    count_sql: str
    select: str
    transform: Callable[[tuple[Any, ...], dict[int, int]], tuple[Any, ...]]


async def main() -> int:
    """Migrate the SQLite database into PostgreSQL (CLI entry)."""
    load_dotenv()
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s] %(message)s"
    )

    password = os.getenv("PGPASSWORD")
    if not password:
        _log.error("PGPASSWORD env var is required")
        return 2
    if not args.gid:
        _log.error("--gid required (or GUILD_ID in .env)")
        return 2

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
    sqlite = sqlite3.connect(f"file:{args.sqlite}?mode=ro", uri=True)
    try:
        archive = load_archive(sqlite)
        uids, cids = collect_ids(sqlite)
        specs = table_specs()
        # counter shape detection:
        #  - counter_event exists: event-based v2 shape, count derived from
        #    the history (one row per press)
        #  - count column exists: pre-event shape, aggregate count stored
        #  - neither: mid-only legacy shape — port presence only, never
        #    touch the v1 counts
        has_events = "counter_event" in {
            r[0]
            for r in sqlite.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        counter_presence = not has_events and not has_column(
            sqlite, "counter", "count"
        )
        if has_events:
            counter_spec = next(s for s in specs if s.name == "counter")
            specs = [
                counter_spec._replace(
                    select=(
                        "SELECT c.mid, COUNT(e.id) FROM counter c"
                        + " LEFT JOIN counter_event e ON e.counter_id = c.id"
                        + " GROUP BY c.id"
                    )
                )
                if s.name == "counter"
                else s
                for s in specs
            ]
        elif counter_presence:
            specs = [s for s in specs if s.name != "counter"]
        if not args.commit:
            await print_plan(pg, sqlite, args.gid, specs, counter_presence)
            _log.info("dry run — pass --commit to write to postgres")
            return 0

        _log.warning(
            "COMMIT MODE — guild %d <- %s on %s:%s/%s "
            + "(single transaction, rolled back on any parity fail)",
            args.gid,
            args.sqlite,
            args.host,
            args.port,
            args.db,
        )
        async with pg.transaction():
            await backfill_support(pg, args.gid, uids, cids)
            for spec in specs:
                info = await replace_table(
                    pg, sqlite, args.gid, spec, archive
                )
                status = (
                    "OK"
                    if info["deleted"] == info["inserted"]
                    else "GROWTH"
                )
                _log.info(
                    "%-16s deleted=%9d inserted=%9d %s",
                    info["table"],
                    info["deleted"],
                    info["inserted"],
                    status,
                )
            if counter_presence:
                info = await port_counter_presence(pg, sqlite, args.gid)
                _log.info(
                    "%-16s deleted=%9s inserted=%9d %s",
                    info["table"],
                    "-",
                    info["inserted"],
                    "PRESENCE",
                )
            problems = await verify_parity(
                pg, sqlite, args.gid, archive, counter_presence
            )
            if problems:
                for p in problems:
                    _log.error("VERIFY FAIL: %s", p)
                raise RuntimeError(
                    "post-write parity failed — transaction rolled back"
                )
        _log.info("committed; all post-write parity checks passed")
        return 0
    finally:
        sqlite.close()
        await pg.close()


async def backfill_support(
    pg: Any, gid: int, uids: list[int], cids: list[int]
) -> None:
    """Insert FK-support rows (guild/user/channel) so the v1 FKs hold.

    The guild row self-heals ``channel.gid -> guild.gid`` and is a no-op
    when v1's config row is already present (it always is).
    """
    await pg.execute(
        "INSERT INTO guild (gid) VALUES ($1) ON CONFLICT DO NOTHING", gid
    )
    for batch in chunks(uids, BATCH):
        await pg.executemany(
            'INSERT INTO "user" (uid) VALUES ($1) ON CONFLICT DO NOTHING',
            [(u,) for u in batch],
        )
    for batch in chunks(cids, BATCH):
        await pg.executemany(
            "INSERT INTO channel (gid, cid) VALUES ($1, $2) "
            + "ON CONFLICT DO NOTHING",
            [(gid, c) for c in batch],
        )
    _log.info(
        "backfilled FK support: %d users, %d channels",
        len(uids),
        len(cids),
    )


async def replace_table(
    pg: Any,
    sqlite: sqlite3.Connection,
    gid: int,
    spec: Table,
    archive: dict[int, int],
) -> dict[str, Any]:
    """Delete the guild's rows, then stream the SQLite contents back in."""
    deleted = int((await pg.execute(spec.delete, gid)).split()[-1])
    inserted = 0
    cur = sqlite.execute(spec.select)
    while True:
        rows = cur.fetchmany(BATCH)
        if not rows:
            break
        await pg.executemany(
            spec.insert, [(gid, *spec.transform(r, archive)) for r in rows]
        )
        inserted += len(rows)
    return {"table": spec.name, "deleted": deleted, "inserted": inserted}


async def port_counter_presence(
    pg: Any, sqlite: sqlite3.Connection, gid: int
) -> dict[str, Any]:
    """Legacy mid-only shape: register sqlite mids, never touch v1 counts.

    Replaces nothing: existing v1 counter rows keep their cutover counts,
    and trial-created counters are inserted with the v1 default (0).
    """
    mids = [r[0] for r in sqlite.execute("SELECT mid FROM counter")]
    inserted = 0
    for batch in chunks(mids, BATCH):
        await pg.executemany(
            "INSERT INTO counter (gid, mid, count) VALUES ($1, $2, 0) "
            + "ON CONFLICT DO NOTHING",
            [(gid, m) for m in batch],
        )
        inserted += len(batch)
    return {"table": "counter", "inserted": inserted}


async def print_plan(
    pg: Any,
    sqlite: sqlite3.Connection,
    gid: int,
    specs: list[Table],
    counter_presence: bool = False,
) -> None:
    """Dry run: show what would be deleted/inserted, write nothing."""
    _log.info("dry-run plan for gid %d (nothing will be written)", gid)
    for spec in specs:
        pg_n = await pg.fetchval(spec.count_sql, gid)
        sl_n = sqlite.execute(
            f"SELECT COUNT(*) FROM {spec.name}"
        ).fetchone()[0]
        _log.info(
            "%-16s pg=%9d sqlite=%9d %s",
            spec.name,
            pg_n,
            sl_n,
            "delete + insert" if pg_n or sl_n else "no-op",
        )
    if counter_presence:
        pg_n = await pg.fetchval(
            "SELECT COUNT(*) FROM counter WHERE gid = $1", gid
        )
        sl_n = sqlite.execute("SELECT COUNT(*) FROM counter").fetchone()[0]
        _log.info(
            "%-16s pg=%9d sqlite=%9d %s",
            "counter",
            pg_n,
            sl_n,
            "insert missing mids (legacy shape)",
        )


async def verify_parity(
    pg: Any,
    sqlite: sqlite3.Connection,
    gid: int,
    archive: dict[int, int],
    counter_presence: bool = False,
) -> list[str]:
    """Per-uid parity of the written tables (PG vs sqlite); runs pre-commit.

    Mirrors ``verify_migration.table_parity`` for the five ported tables.
    """
    problems: list[str] = []

    # member_exp: exact (uid, lifetime, msg_cnt) equality
    pg_rows = await pg.fetch(
        "SELECT uid, lifetime, msg_cnt FROM member_exp WHERE gid = $1", gid
    )
    sl_rows = sqlite.execute(
        "SELECT uid, lifetime, msg_cnt FROM member_exp"
    ).fetchall()
    pg_set = {(r["uid"], r["lifetime"], r["msg_cnt"]) for r in pg_rows}
    sl_set = {tuple(r) for r in sl_rows}
    if pg_set != sl_set:
        problems.append(
            f"member_exp: {len(pg_set)} pg rows != {len(sl_set)} sqlite"
        )

    # member_exp_log: per-uid row count + exp sum
    pg_rows = await pg.fetch(
        "SELECT uid, COUNT(*) AS n, COALESCE(SUM(exp), 0) AS s "
        + "FROM member_exp_log WHERE gid = $1 GROUP BY uid",
        gid,
    )
    sl_rows = sqlite.execute(
        "SELECT uid, COUNT(*), COALESCE(SUM(exp), 0) "
        + "FROM member_exp_log GROUP BY uid"
    ).fetchall()
    pg_set = {(r["uid"], r["n"], int(r["s"])) for r in pg_rows}
    sl_set = {(r[0], r[1], int(r[2])) for r in sl_rows}
    if pg_set != sl_set:
        problems.append(
            "member_exp_log: per-uid (count, sum) differs "
            + f"(pg={len(pg_set)} uids, sqlite={len(sl_set)})"
        )

    # member_frog: exact balances + deprecated_normal restored
    pg_rows = await pg.fetch(
        "SELECT uid, normal, frozen, capture, deprecated_normal "
        + "FROM member_frog WHERE gid = $1",
        gid,
    )
    sl_rows = sqlite.execute(
        "SELECT uid, normal, frozen, capture FROM member_frog"
    ).fetchall()
    pg_set = {
        (r["uid"], r["normal"], r["frozen"], r["capture"]) for r in pg_rows
    }
    sl_set = {tuple(r) for r in sl_rows}
    if pg_set != sl_set:
        problems.append(
            f"member_frog: {len(pg_set)} pg rows != {len(sl_set)} sqlite"
        )
    pg_dep = {r["uid"]: r["deprecated_normal"] for r in pg_rows}
    for uid, dep in archive.items():
        if pg_dep.get(uid) != dep:
            problems.append(
                f"member_frog.deprecated_normal: uid {uid} "
                + f"is {pg_dep.get(uid)}, archive has {dep}"
            )

    # member_frog_log: per-uid count exact, waited_for sum within float tol
    pg_rows = await pg.fetch(
        "SELECT uid, COUNT(*) AS n, COALESCE(SUM(waited_for), 0) AS w "
        + "FROM member_frog_log WHERE gid = $1 OR gid IS NULL GROUP BY uid",
        gid,
    )
    sl_rows = sqlite.execute(
        "SELECT uid, COUNT(*), COALESCE(SUM(waited_for), 0) "
        + "FROM member_frog_log GROUP BY uid"
    ).fetchall()
    pg_map = {r["uid"]: (r["n"], r["w"]) for r in pg_rows}
    sl_map = {r[0]: (r[1], r[2]) for r in sl_rows}
    bad = 0
    for uid, (n, w) in sl_map.items():
        p = pg_map.get(uid)
        if p is None or p[0] != n:
            bad += 1
            continue
        if abs(p[1] - w) > 1e-5 * max(1.0, abs(p[1]), abs(w)):
            bad += 1
    if bad or set(pg_map) != set(sl_map):
        problems.append(
            f"member_frog_log: {bad} uid mismatches "
            + f"(pg={len(pg_map)}, sqlite={len(sl_map)})"
        )

    # frog_spawn: exact equality, fuzzy rounded to float4 precision
    pg_rows = await pg.fetch(
        'SELECT cid, "interval", persist, fuzzy FROM frog_spawn '
        + "WHERE gid = $1",
        gid,
    )
    sl_rows = sqlite.execute(
        'SELECT cid, "interval", persist, fuzzy FROM frog_spawn'
    ).fetchall()
    pg_set = {
        (r["cid"], r["interval"], r["persist"], round(r["fuzzy"], 6))
        for r in pg_rows
    }
    sl_set = {(r[0], r[1], r[2], round(r[3], 6)) for r in sl_rows}
    if pg_set != sl_set:
        problems.append(
            f"frog_spawn: {len(pg_set)} pg rows != {len(sl_set)} sqlite"
        )

    # counter: exact (mid, count) equality, or presence-only legacy shape
    if counter_presence:
        sl_mids = {r[0] for r in sqlite.execute("SELECT mid FROM counter")}
        pg_rows = await pg.fetch(
            "SELECT mid FROM counter WHERE gid = $1", gid
        )
        missing = sl_mids - {r["mid"] for r in pg_rows}
        if missing:
            problems.append(
                f"counter: {len(missing)} mids not registered "
                + f"({sorted(missing)[:5]})"
            )
    else:
        pg_rows = await pg.fetch(
            "SELECT mid, count FROM counter WHERE gid = $1", gid
        )
        if "counter_event" in {
            r[0]
            for r in sqlite.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }:
            # event-based shape: derive the count from the history
            sl_rows = sqlite.execute(
                "SELECT c.mid, COUNT(e.id) FROM counter c"
                + " LEFT JOIN counter_event e ON e.counter_id = c.id"
                + " GROUP BY c.mid"
            ).fetchall()
        else:
            sl_rows = sqlite.execute(
                "SELECT mid, count FROM counter"
            ).fetchall()
        pg_set = {(r["mid"], r["count"]) for r in pg_rows}
        sl_set = {tuple(r) for r in sl_rows}
        if pg_set != sl_set:
            problems.append(
                f"counter: {len(pg_set)} pg rows != {len(sl_set)} sqlite"
            )

    return problems


# -- helpers ---------------------------------------------------------------


def ts(value: Any) -> Any:
    """SQLite ISO string | None -> aware datetime | None (sentinel -> NULL)."""
    if value is None or value == SENTINEL_AT:
        return None
    return pendulum.parse(value)


def exp_row(
    r: tuple[Any, ...], _archive: dict[int, int]
) -> tuple[Any, ...]:
    """Map a SQLite member-exp row to the v1 column order."""
    uid, lifetime, msg_cnt, cdr = r
    return (uid, lifetime, msg_cnt, ts(cdr))


def exp_log_row(
    r: tuple[Any, ...], _archive: dict[int, int]
) -> tuple[Any, ...]:
    """Map a SQLite exp-log row to the v1 column order."""
    uid, exp, at, source = r
    return (uid, exp, ts(at), source)


def frog_row(
    r: tuple[Any, ...], archive: dict[int, int]
) -> tuple[Any, ...]:
    """Map a SQLite frog row to v1 order (restoring the retired column)."""
    uid, normal, frozen, capture = r
    # restore the retired pre-split column from the forward archive
    return (uid, archive.get(uid, 0), frozen, capture, normal)


def frog_log_row(
    r: tuple[Any, ...], _archive: dict[int, int]
) -> tuple[Any, ...]:
    """Map a SQLite frog-log row to the v1 column order."""
    uid, log_type, at, waited_for = r
    # v1 column order is (gid, uid, at, type, waited_for)
    return (uid, ts(at), log_type, waited_for)


def spawn_row(
    r: tuple[Any, ...], _archive: dict[int, int]
) -> tuple[Any, ...]:
    """Map a SQLite frog-spawn row to the v1 column order."""
    cid, interval, persist, fuzzy = r
    return (cid, interval, persist, float(fuzzy))


def counter_row(
    r: tuple[Any, ...], _archive: dict[int, int]
) -> tuple[Any, ...]:
    """Map a SQLite counter row to the v1 column order."""
    mid, count = r
    return (mid, count)


def table_specs() -> list[Table]:
    """The five ported tables: pg write specs + sqlite source queries."""
    return [
        Table(
            "member_exp",
            "DELETE FROM member_exp WHERE gid = $1",
            "INSERT INTO member_exp (gid, uid, lifetime, msg_cnt, cdr) "
            + "VALUES ($1, $2, $3, $4, $5)",
            "SELECT COUNT(*) FROM member_exp WHERE gid = $1",
            "SELECT uid, lifetime, msg_cnt, cdr FROM member_exp",
            exp_row,
        ),
        Table(
            "member_exp_log",
            "DELETE FROM member_exp_log WHERE gid = $1",
            "INSERT INTO member_exp_log (gid, uid, exp, at, source) "
            + "VALUES ($1, $2, $3, $4, $5)",
            "SELECT COUNT(*) FROM member_exp_log WHERE gid = $1",
            "SELECT uid, exp, at, source FROM member_exp_log",
            exp_log_row,
        ),
        Table(
            "member_frog",
            "DELETE FROM member_frog WHERE gid = $1",
            "INSERT INTO member_frog "
            + "(gid, uid, deprecated_normal, frozen, capture, normal) "
            + "VALUES ($1, $2, $3, $4, $5, $6)",
            "SELECT COUNT(*) FROM member_frog WHERE gid = $1",
            "SELECT uid, normal, frozen, capture FROM member_frog",
            frog_row,
        ),
        Table(
            "member_frog_log",
            "DELETE FROM member_frog_log WHERE gid = $1 OR gid IS NULL",
            "INSERT INTO member_frog_log (gid, uid, at, type, waited_for) "
            + "VALUES ($1, $2, $3, $4, $5)",
            "SELECT COUNT(*) FROM member_frog_log "
            + "WHERE gid = $1 OR gid IS NULL",
            "SELECT uid, type, at, waited_for FROM member_frog_log",
            frog_log_row,
        ),
        Table(
            "frog_spawn",
            "DELETE FROM frog_spawn WHERE gid = $1",
            'INSERT INTO frog_spawn (gid, cid, "interval", persist, fuzzy) '
            + "VALUES ($1, $2, $3, $4, $5)",
            "SELECT COUNT(*) FROM frog_spawn WHERE gid = $1",
            'SELECT cid, "interval", persist, fuzzy FROM frog_spawn',
            spawn_row,
        ),
        Table(
            "counter",
            "DELETE FROM counter WHERE gid = $1",
            "INSERT INTO counter (gid, mid, count) VALUES ($1, $2, $3)",
            "SELECT COUNT(*) FROM counter WHERE gid = $1",
            "SELECT mid, count FROM counter",
            counter_row,
        ),
    ]


def has_column(
    sqlite: sqlite3.Connection, table: str, column: str
) -> bool:
    """True if ``table`` has ``column`` (the schema may predate the DDL)."""
    return any(
        row[1] == column
        for row in sqlite.execute(f"PRAGMA table_info({table})")
    )


def load_archive(sqlite: sqlite3.Connection) -> dict[int, int]:
    """uid -> deprecated_normal from the forward migration's archive table."""
    archive: dict[int, int] = {}
    try:
        rows = sqlite.execute(
            "SELECT uid, deprecated_normal "
            + "FROM _archive_member_frog_deprecated_normal"
        )
    except sqlite3.OperationalError:
        return (
            archive  # absent on DBs that never ran the forward migration
        )
    for uid, dep in rows:
        archive[uid] = dep
    return archive


def collect_ids(
    sqlite: sqlite3.Connection,
) -> tuple[list[int], list[int]]:
    """Distinct uids (exp/frog) and cids (frog_spawn) for FK backfill."""
    uids: set[int] = set()
    for tbl in (
        "member_exp",
        "member_exp_log",
        "member_frog",
        "member_frog_log",
    ):
        for (uid,) in sqlite.execute(f"SELECT DISTINCT uid FROM {tbl}"):
            uids.add(uid)
    cids = {
        c for (c,) in sqlite.execute("SELECT DISTINCT cid FROM frog_spawn")
    }
    return sorted(uids), sorted(cids)


def chunks(seq: list[int], size: int) -> Iterator[list[int]]:
    """Yield ``seq`` in slices of at most ``size``."""
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def parse_args() -> argparse.Namespace:
    """Parse the migration's CLI arguments."""
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
        "--sqlite",
        default="data/cazzubot-prod.db",
        help="v2 sqlite db path (default: data/cazzubot-prod.db)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="actually write to postgres (default: dry run)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
