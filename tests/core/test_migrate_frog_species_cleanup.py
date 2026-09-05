"""Frog species-key fold migration — retired keys → current species.

Builds a DB in the current shape (generic inventory DDL + the rebuilt
``member_frog_log`` with the ``'basic'`` type default) carrying legacy-key
stacks from the two key regimes (``classy_frog`` / ``leaf_frog``), runs
the migration logic directly (no CLI), and asserts the fold: quantities
**merge** into the current species' stacks (never overwrite, even when the
member holds the same species under both keys), legacy rows are gone, and
capture-log types are rewritten to the current keys.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.migrations.frog_species_cleanup import (
    SPECIES_RENAMES,
    migrate,
    needs_cleanup,
    plan,
)

# the generic inventory DDL and the rebuilt log table, mirroring the
# post-003/005 shapes exactly (the boot schema guard compares DDL).
_INVENTORY_DDL = """
CREATE TABLE IF NOT EXISTS inventory (
    uid  INTEGER NOT NULL,
    item TEXT NOT NULL,
    qty  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (uid, item)
)
"""

_LOG_DDL = """
CREATE TABLE member_frog_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        INTEGER NOT NULL,
    type       TEXT NOT NULL DEFAULT 'basic',
    at         TEXT NOT NULL,
    waited_for REAL
)
"""


def _current_shape_conn(path: Path) -> sqlite3.Connection:
    """A DB in the current shape with mixed legacy/current frog keys:
    uid 1 holds classy frogs under both the legacy and current keys (the
    fold must SUM to one stack), uid 2 a frozen leaf_frog stack, and the
    log mixes legacy and current types."""
    conn = sqlite3.connect(path)
    conn.execute(_INVENTORY_DDL)
    conn.execute(_LOG_DDL)
    for uid, item, qty in (
        (1, "frog:classy:normal", 2),  # current key (new catches)
        (1, "frog:classy_frog:normal", 4),  # legacy key (old catches)
        (2, "frog:leaf_frog:frozen", 3),  # legacy key (pre-rename)
        (2, "frog:basic:frozen", 1),  # current key
        (3, "frog:pog:normal", 7),  # unaffected species
    ):
        conn.execute(
            "INSERT INTO inventory (uid, item, qty) VALUES (?, ?, ?)",
            (uid, item, qty),
        )
    for uid, kind, at in (
        (1, "basic", "2026-01-01T00:00:00+00:00"),
        (1, "classy_frog", "2026-01-02T00:00:00+00:00"),
        (1, "classy", "2026-01-03T00:00:00+00:00"),
        (2, "leaf_frog", "2026-01-04T00:00:00+00:00"),
        (3, "pog", "2026-01-05T00:00:00+00:00"),
    ):
        conn.execute(
            "INSERT INTO member_frog_log (uid, type, at, waited_for) "
            + "VALUES (?, ?, ?, 1.5)",
            (uid, kind, at),
        )
    conn.commit()
    return conn


def test_needs_and_plan_report_exact_counts(tmp_path: Path) -> None:
    conn = _current_shape_conn(tmp_path / "legacy.db")
    try:
        assert needs_cleanup(conn) is True
        report = plan(conn)
        assert report.inventory_rows == 2  # classy_frog + leaf_frog stacks
        assert report.log_rows == 2  # classy_frog + leaf_frog types
    finally:
        conn.close()


def test_migrate_folds_quantities_and_rewrites_logs(
    tmp_path: Path,
) -> None:
    conn = _current_shape_conn(tmp_path / "legacy.db")
    try:
        report = migrate(conn)
        assert report.inventory_rows == 2 and report.log_rows == 2, report

        rows = conn.execute(
            "SELECT uid, item, qty FROM inventory ORDER BY uid, item"
        ).fetchall()
        assert rows == [
            (1, "frog:classy:normal", 6),  # 2 current + 4 folded legacy
            (2, "frog:basic:frozen", 4),  # 1 current + 3 folded legacy
            (3, "frog:pog:normal", 7),  # untouched
        ], rows
        # every legacy key is gone
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM inventory WHERE item NOT IN "
                + "('frog:classy:normal', 'frog:basic:frozen', "
                + "'frog:pog:normal')"
            ).fetchone()[0]
            == 0
        )
        # log types rewritten to the current keys, others untouched
        types = [
            r[0]
            for r in conn.execute(
                "SELECT type FROM member_frog_log ORDER BY id"
            )
        ]
        assert types == [
            "basic",
            "classy",  # was classy_frog
            "classy",
            "basic",  # was leaf_frog
            "pog",
        ], types
        assert needs_cleanup(conn) is False
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = _current_shape_conn(tmp_path / "legacy.db")
    try:
        migrate(conn)
        # the idempotence gate: no legacy values remain, so a second run is
        # a no-op (and never re-sums the already-folded stacks)
        assert needs_cleanup(conn) is False
        rows = conn.execute(
            "SELECT uid, item, qty FROM inventory ORDER BY uid, item"
        ).fetchall()
        assert rows == [
            (1, "frog:classy:normal", 6),
            (2, "frog:basic:frozen", 4),
            (3, "frog:pog:normal", 7),
        ], rows
    finally:
        conn.close()


def test_needs_false_without_legacy_keys(tmp_path: Path) -> None:
    """A fresh DB (no tables) and a DB without legacy keys both skip."""
    fresh = sqlite3.connect(tmp_path / "fresh.db")
    try:
        assert needs_cleanup(fresh) is False
    finally:
        fresh.close()

    clean = sqlite3.connect(tmp_path / "clean.db")
    try:
        clean.execute(_INVENTORY_DDL)
        clean.execute(_LOG_DDL)
        clean.execute(
            "INSERT INTO inventory (uid, item, qty) VALUES (1, ?, 5)",
            (f"frog:{SPECIES_RENAMES['classy_frog']}:normal",),
        )
        clean.commit()
        assert needs_cleanup(clean) is False  # only current keys present
    finally:
        clean.close()
