"""Migration: legacy counter tables -> event-based counter tables.

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

Idempotent: ``needs_migration`` is False once ``counter_event`` exists or
``counter`` has no stored ``count`` column. Parity is verified INSIDE the
migration transaction (any mismatch rolls the whole thing back). Run
through ``scripts/migrate.py`` (all pending) or the thin wrapper
``scripts/migrate_counter_events.py``; dry-run by default, ``--commit`` to
write, backup before mutation, bot stopped.

Call graph: ``MIGRATION`` registers this module with the shared harness;
tests drive ``needs_migration`` / ``plan`` / ``migrate`` directly against a
temp legacy DB.
"""

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.migrations.common import Migration  # noqa: E402
from plugins.counter.db import SCHEMA as _COUNTER_SCHEMA  # noqa: E402

EPOCH = "1970-01-01T00:00:00+00:00"


@dataclass(frozen=True, slots=True)
class CounterPlan:
    """What the migration found — the dry-run report."""

    counters: int  # counter registry rows to create
    total_events: int  # events (real + backfilled) to insert


def _load(
    conn: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    """Legacy counter rows plus per-mid baka rows, both ordered by mid.

    Reads by column position so the module works whether or not the caller
    set ``row_factory`` (the runner does; direct test connections may not).
    """
    counters = [
        {"mid": r[0], "count": r[1]}
        for r in conn.execute(
            "SELECT mid, count FROM counter ORDER BY mid"
        )
    ]
    by_mid: dict[int, list[dict[str, Any]]] = {}
    for r in conn.execute(
        "SELECT mid, uid, name, updated_at FROM counter_baka"
    ):
        by_mid.setdefault(r[0], []).append(
            {"mid": r[0], "uid": r[1], "name": r[2], "updated_at": r[3]}
        )
    return counters, by_mid


def needs_migration(conn: sqlite3.Connection) -> bool:
    """True when the legacy aggregate shape is present.

    Legacy = ``counter`` exists with a stored ``count`` column and there is
    no ``counter_event`` table yet. The idempotence gate: after the
    migration (or on the mid-only / event-based shapes) this is False.
    """
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    if "counter_event" in tables or "counter" not in tables:
        return False
    cols = {r[1] for r in conn.execute("PRAGMA table_info(counter)")}
    return "count" in cols


def plan(conn: sqlite3.Connection) -> CounterPlan:
    """Read-only counts of what :func:`migrate` would do."""
    counters, by_mid = _load(conn)
    total = 0
    for c in counters:
        real = len(by_mid.get(c["mid"], []))
        total += real + max(0, c["count"] - real)
    return CounterPlan(counters=len(counters), total_events=total)


def migrate(conn: sqlite3.Connection) -> CounterPlan:
    """Rebuild the tables in one transaction; returns what it did.

    The legacy aggregate shapes are recreated from the plugin's own DDL so
    boot-time schema parity holds; per-mid derived event totals are checked
    against the legacy ``count`` values before commit.
    """
    before = plan(conn)
    counters, by_mid = _load(conn)
    conn.execute("BEGIN")
    try:
        # keep the old table's data under a temp name, then recreate the
        # new shape from the plugin's own DDL
        conn.execute("ALTER TABLE counter RENAME TO counter_legacy")
        for statement in _COUNTER_SCHEMA:
            conn.execute(statement)

        # registry rows first (the events fkey to counter.id); both lists
        # are ordered by mid so the ids line up with the legacy rows
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
            rows.extend(
                (new_id, None, None, EPOCH) for _ in range(backfill)
            )
        conn.executemany(
            "INSERT INTO counter_event (counter_id, uid, name, updated_at)"
            + " VALUES (?, ?, ?, ?)",
            rows,
        )

        conn.execute("DROP TABLE counter_legacy")
        conn.execute("DROP TABLE counter_baka")

        _verify(conn, counters)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return before


def _verify(
    conn: sqlite3.Connection, counters: list[dict[str, Any]]
) -> None:
    """Every counter's derived event total must equal the old stored count."""
    got = {
        int(r[0]): int(r[1])
        for r in conn.execute(
            "SELECT c.mid, COUNT(e.id) AS n FROM counter c"
            + " LEFT JOIN counter_event e ON e.counter_id = c.id"
            + " GROUP BY c.id"
        )
    }
    for c in counters:
        if got.get(c["mid"]) != c["count"]:
            raise RuntimeError(
                f"mid {c['mid']}: expected {c['count']} events, "
                + f"got {got.get(c['mid'])}"
            )


MIGRATION = Migration(
    id="002_counter_events",
    doc="convert aggregate counter tables into per-press counter_event rows",
    needs=needs_migration,
    plan=plan,
    summary=lambda p: (
        f"convert {p.counters} counter(s) into {p.total_events} event(s)"
    ),
    migrate=migrate,
)
