#!/bin/env python
"""Post-migration verification: migrated SQLite vs live PostgreSQL + bot paths.

Compares every table's data per-uid against the live PostgreSQL source,
exercises v2's own derivation paths (seasonal rankings, ``sync_with_exp_logs``,
``sync_with_frog_logs`` on a throwaway copy — the real file is never mutated),
checks settings round-trip through v2's ``Settings``, and validates poll
integrity after the item-id renumbering.

Usage::

    PGPASSWORD=... uv run --group migration python scripts/verify_migration.py
                           [--gid 293796316193095690] [--db data/cazzubot.migrated.db]
"""

import argparse
import asyncio
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

# make the project root importable when run as ``python scripts/<name>.py``
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncpg
import pendulum
from dotenv import load_dotenv

from cazzubot.db import Database
from cazzubot.settings import Settings
from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db

_log = logging.getLogger("verify_migration")

FAILS: list[str] = []


def check(cond: bool, label: str, detail: str = "") -> None:
    status = "ok  " if cond else "FAIL"
    if not cond:
        FAILS.append(label)
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))


def norm(v: Any) -> Any:
    """Normalize a value for PG-vs-sqlite row comparison."""
    if v is None:
        return ""
    if v is True:
        return 1
    if v is False:
        return 0
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


async def table_parity(
    pg: Any, sqlite: sqlite3.Connection, gid: int
) -> None:
    """Compare full per-uid aggregates between postgres and sqlite."""

    def sql_map(rows: Any, keys: tuple[str, ...]) -> dict[Any, Any]:
        out: dict[Any, Any] = {}
        for r in rows:
            k = tuple(r[k] for k in keys)
            out[k[0] if len(k) == 1 else k] = r
        return out

    print("== full per-uid parity (postgres vs sqlite) ==")

    # member_exp: lifetime, msg_cnt (cdr compared as counts only)
    pg_rows = await pg.fetch(
        "SELECT uid, lifetime, msg_cnt FROM member_exp WHERE gid = $1", gid
    )
    pg_map = sql_map(pg_rows, ("uid",))
    sl_rows = sqlite.execute(
        "SELECT uid, lifetime, msg_cnt FROM member_exp"
    ).fetchall()
    sl_map = {r[0]: r for r in sl_rows}
    bad = 0
    for uid, r in pg_map.items():
        s = sl_map.get(uid)
        if s is None or (s[1], s[2]) != (r["lifetime"], r["msg_cnt"]):
            bad += 1
    check(
        bad == 0 and len(pg_map) == len(sl_map),
        "member_exp (lifetime, msg_cnt)",
        f"{len(pg_map)} uids, {bad} mismatches",
    )

    # member_exp_log aggregates: COUNT, SUM(exp)
    # (dated-row count intentionally differs: 5680 NULL-at rows are sentineled)
    pg_rows = await pg.fetch(
        "SELECT uid, COUNT(*) AS n, SUM(exp) AS s "
        + "FROM member_exp_log WHERE gid = $1 GROUP BY uid",
        gid,
    )
    pg_map = sql_map(pg_rows, ("uid",))
    sl_rows = sqlite.execute(
        "SELECT uid, COUNT(*), SUM(exp) FROM member_exp_log GROUP BY uid"
    ).fetchall()
    sl_map = {r[0]: r for r in sl_rows}
    bad = 0
    for uid, r in pg_map.items():
        s = sl_map.get(uid)
        if s is None or (s[1], s[2]) != (r["n"], int(r["s"] or 0)):
            bad += 1
    check(
        bad == 0 and len(pg_map) == len(sl_map),
        "member_exp_log (COUNT, SUM(exp))",
        f"{len(pg_map)} uids, {bad} mismatches",
    )

    # member_frog: normal, frozen, capture
    pg_rows = await pg.fetch(
        "SELECT uid, COALESCE(normal,0) AS normal, COALESCE(frozen,0) AS frozen, "
        + "COALESCE(capture,0) AS capture FROM member_frog WHERE gid = $1",
        gid,
    )
    pg_map = sql_map(pg_rows, ("uid",))
    sl_rows = sqlite.execute(
        "SELECT uid, normal, frozen, capture FROM member_frog"
    ).fetchall()
    sl_map = {r[0]: r for r in sl_rows}
    bad = 0
    for uid, r in pg_map.items():
        s = sl_map.get(uid)
        if s is None or (s[1], s[2], s[3]) != (
            r["normal"],
            r["frozen"],
            r["capture"],
        ):
            bad += 1
    check(
        bad == 0 and len(pg_map) == len(sl_map),
        "member_frog (normal, frozen, capture)",
        f"{len(pg_map)} uids, {bad} mismatches",
    )

    # member_frog_log aggregates: COUNT exact, SUM(waited_for) within tolerance
    # (PG float4 vs SQLite REAL precision)
    pg_rows = await pg.fetch(
        "SELECT uid, COUNT(*) AS n, COALESCE(SUM(waited_for),0) AS w "
        + "FROM member_frog_log WHERE gid = $1 OR gid IS NULL GROUP BY uid",
        gid,
    )
    pg_map = sql_map(pg_rows, ("uid",))
    sl_rows = sqlite.execute(
        "SELECT uid, COUNT(*), COALESCE(SUM(waited_for),0) "
        + "FROM member_frog_log GROUP BY uid"
    ).fetchall()
    sl_map = {r[0]: r for r in sl_rows}
    bad = 0
    for uid, r in pg_map.items():
        s = sl_map.get(uid)
        if s is None or s[1] != r["n"]:
            bad += 1
            continue
        # float32 storage in PG vs float64 in sqlite -> tiny summation drift
        if abs(s[2] - float(r["w"])) > 1e-5 * max(
            1.0, abs(s[2]), abs(float(r["w"]))
        ):
            bad += 1
    check(
        bad == 0 and len(pg_map) == len(sl_map),
        "member_frog_log (COUNT, SUM(waited_for))",
        f"{len(pg_map)} uids, {bad} mismatches",
    )

    # small tables: exact row equality (sorted); modlog.case_id maps to v2 id
    for table, cols in (
        ("frog_spawn", ("cid", "interval", "persist", "fuzzy")),
        ("rank_threshold", ("rid", "threshold", "mode")),
        (
            "modlog",
            (
                "case_id",
                "uid",
                "log_type",
                "given_on",
                "status",
                "expires_on",
                "reason",
            ),
        ),
        ("counter", ("mid", "count")),
        (
            "poll",
            ("id", "title", "description", "max_vote", "mid", "open"),
        ),
    ):
        pg_rows = await pg.fetch(
            f"SELECT {', '.join(cols)} FROM {table} WHERE gid = $1", gid
        )
        pg_set = {tuple(norm(v) for v in r) for r in pg_rows}
        sl_cols = (
            ", ".join(cols).replace("case_id", "id")
            if table == "modlog"
            else ", ".join(cols)
        )
        sl_rows = sqlite.execute(
            f"SELECT {sl_cols} FROM {table}"
        ).fetchall()
        sl_set = {tuple(norm(v) for v in r) for r in sl_rows}
        check(
            pg_set == sl_set,
            table,
            f"pg={len(pg_set)} sqlite={len(sl_set)}",
        )


async def seasonal_parity(pg: Any, db: Database, gid: int) -> None:
    """Compare v2 seasonal rankings (migrated DB) against postgres sums.

    ``db`` is a ``cazzubot.db.Database`` so v2's own query paths run verbatim.
    """
    print("== seasonal leaderboard parity (v2 path vs postgres) ==")
    for year, season in ((2023, 3), (2025, 0), (2026, 1), (2026, 2)):
        start = pendulum.datetime(year, 1 + 3 * season, 1, tz="UTC")
        end = start.add(months=3)
        pg_rows = await pg.fetch(
            "SELECT uid, SUM(exp) AS exp FROM member_exp_log "
            + "WHERE gid = $1 AND at >= $2 AND at < $3 "
            + "GROUP BY uid ORDER BY exp DESC",
            gid,
            start,
            end,
        )
        pg_pairs = [(r["uid"], int(r["exp"])) for r in pg_rows]
        v2 = await exp_db.seasonal_ranked(db, year, season)
        v2_pairs = [(uid, exp) for _, uid, exp in v2]
        top = min(25, len(pg_pairs))
        check(
            pg_pairs[:top] == v2_pairs[:top]
            and len(pg_pairs) == len(v2_pairs),
            f"season {year}-Q{season + 1}",
            f"pg={len(pg_pairs)} v2={len(v2_pairs)}, top {top} equal",
        )


async def resync_no_drift(path: Path) -> None:
    """Run v2's own resync paths on a copy; the real file is never mutated."""
    print("== v2 resync paths on a copy (expect ~zero drift) ==")
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "copy.db"
        shutil.copy2(path, copy)

        def snapshot(
            conn: sqlite3.Connection,
        ) -> tuple[dict[Any, Any], dict[Any, Any]]:
            exp = dict(
                conn.execute(
                    "SELECT uid, lifetime FROM member_exp"
                ).fetchall()
            )
            frog = dict(
                conn.execute(
                    "SELECT uid, capture FROM member_frog"
                ).fetchall()
            )
            return exp, frog

        conn = sqlite3.connect(copy)
        exp_before, frog_before = snapshot(conn)
        conn.close()

        db = Database(str(copy))
        await db.connect()
        await exp_db.sync_with_exp_logs(db)
        await frog_db.sync_with_frog_logs(db)
        await db.close()

        conn = sqlite3.connect(copy)
        exp_after, frog_after = snapshot(conn)
        conn.close()

        exp_drift = [
            uid
            for uid in exp_before
            if exp_before[uid] != exp_after.get(uid)
        ]
        frog_drift = [
            uid
            for uid in frog_before
            if frog_before[uid] != frog_after.get(uid)
        ]
        check(
            not exp_drift,
            "sync_with_exp_logs drift",
            f"{len(exp_drift)} uids changed"
            if exp_drift
            else "0 uids changed",
        )
        check(
            len(frog_drift) <= 1,
            "sync_with_frog_logs drift",
            f"{len(frog_drift)} uids changed (expected <=1: capture is a "
            + "lifetime counter, logs may predate it / NULL-gid attributed)",
        )
        if frog_drift:
            detail = ", ".join(
                f"{u}: {frog_before[u]} -> {frog_after[u]}"
                for u in frog_drift[:5]
            )
            print(f"     (frog drift detail: {detail})")


async def settings_check(path: Path) -> None:
    print("== settings round-trip through v2 Settings ==")
    db = Database(str(path))
    await db.connect()
    settings = Settings(db)
    all_settings = await settings.all()
    for key in sorted(all_settings):
        val = all_settings[key]
        print(f"  {key:36} {str(val)[:80]}")
    expected = {
        "inktober.cid": 1291176007184809996,
        "frog.enabled": True,
        "level.quiet": [704847575970349106],
        "rank.seasonal.enabled": True,
        "rank.seasonal.keep_old": True,
        "rank.lifetime.enabled": True,
        "welcome.enabled": True,
        "welcome.mode": "pending",
        "daily.last_daily": "2026-08-05T00:00:00.400093+00:00",
        "quarterly.last_quarterly": "2025-12-10T21:35:43.784501+00:00",
    }
    for key, want in expected.items():
        check(
            all_settings.get(key) == want,
            f"settings.{key}",
            f"{all_settings.get(key)!r}",
        )
    await db.close()


def poll_integrity(path: Path) -> None:
    print("== poll integrity after item-id renumbering ==")
    conn = sqlite3.connect(path)
    votes_orphan_poll = conn.execute(
        "SELECT COUNT(*) FROM poll_vote v "
        + "WHERE NOT EXISTS (SELECT 1 FROM poll p WHERE p.id = v.pid)"
    ).fetchone()[0]
    votes_orphan_item = conn.execute(
        "SELECT COUNT(*) FROM poll_vote v "
        + "WHERE NOT EXISTS "
        + "(SELECT 1 FROM poll_item i WHERE i.id = v.iid AND i.pid = v.pid)"
    ).fetchone()[0]
    itemless_polls = conn.execute(
        "SELECT COUNT(*) FROM poll p "
        + "WHERE NOT EXISTS (SELECT 1 FROM poll_item i WHERE i.pid = p.id)"
    ).fetchone()[0]
    dupe_votes = conn.execute(
        "SELECT COUNT(*) FROM (SELECT 1 FROM poll_vote "
        + "GROUP BY pid, iid, uid HAVING COUNT(*) > 1)"
    ).fetchone()[0]
    check(
        votes_orphan_poll == 0,
        "votes reference existing polls",
        f"{votes_orphan_poll}",
    )
    check(
        votes_orphan_item == 0,
        "votes reference existing items",
        f"{votes_orphan_item}",
    )
    check(itemless_polls == 0, "polls have items", f"{itemless_polls}")
    check(dupe_votes == 0, "poll_vote PK unique", f"{dupe_votes}")
    rows = conn.execute(
        "SELECT p.id, COUNT(DISTINCT i.id) AS items, "
        + "(SELECT COUNT(*) FROM poll_vote v WHERE v.pid = p.id) AS votes "
        + "FROM poll p LEFT JOIN poll_item i ON i.pid = p.id GROUP BY p.id "
        + "ORDER BY p.id"
    ).fetchall()
    for r in rows:
        print(f"  poll {r[0]:>3}: items={r[1]:>3} votes={r[2]:>4}")
    conn.close()


async def main() -> int:
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
        "--sqlite",
        default="data/cazzubot.migrated.db",
        help="migrated db path",
    )
    args = parser.parse_args()

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
            password=os.getenv("PGPASSWORD"),
            database=args.db,
            ssl=False,
            timeout=15,
        ),
    )
    sqlite = sqlite3.connect(args.sqlite)
    path = Path(args.sqlite)
    db = Database(str(path))
    await db.connect()

    await table_parity(pg, sqlite, args.gid)
    await seasonal_parity(pg, db, args.gid)
    await resync_no_drift(path)
    await settings_check(path)
    poll_integrity(path)

    conn = sqlite3.connect(path)
    tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    conn.close()
    check(tasks == 0, "tasks table empty (re-scheduled at boot)")

    await db.close()
    sqlite.close()
    await pg.close()

    print()
    if FAILS:
        print(f"VERIFICATION FAILED ({len(FAILS)}):")
        for f in FAILS:
            print("  -", f)
        return 1
    print("ALL VERIFICATION CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
