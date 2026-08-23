"""Migration harness — shared runner behavior plus the ported counter-events
migration.

The five migration modules (poll_cid / counter_events / frog_species /
asset_kind / frog_species_key) are individually covered in
``test_rename_*.py`` and ``test_migrate_frog_species.py``; this file tests
the pieces those do not: the registry order, the runner's dry-run /
commit / backup / no-op contract (``run_one``), the ``scripts/migrate.py``
CLI (``--list``, ``--only``), and the counter-events module that no longer
has its old standalone tests.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import scripts.migrate as runner
from scripts.migrations import MIGRATIONS
from scripts.migrations.common import run_one
from scripts.migrations.counter_events import (
    EPOCH,
    migrate as migrate_counter_events,
    needs_migration as counter_needs_migration,
    plan as counter_plan,
)
from scripts.migrations.poll_cid import MIGRATION as POLL_MIGRATION

_POLL_DDL = """
CREATE TABLE poll (
    id          INTEGER PRIMARY KEY,
    uid         INTEGER NOT NULL,
    title       TEXT NOT NULL,
    open        INTEGER NOT NULL,
    description TEXT NOT NULL
)
"""

_LEGACY_COUNTER_DDL = """
CREATE TABLE counter (
    mid   INTEGER PRIMARY KEY,
    count INTEGER NOT NULL
)
"""

_LEGACY_BAKA_DDL = """
CREATE TABLE counter_baka (
    mid        INTEGER NOT NULL,
    uid        INTEGER NOT NULL,
    name       TEXT,
    updated_at TEXT NOT NULL
)
"""


def _legacy_poll_db(path: Path) -> sqlite3.Connection:
    """A poll table without the ``cid`` column (the legacy shape)."""
    conn = sqlite3.connect(path)
    conn.execute(_POLL_DDL)
    conn.executemany(
        "INSERT INTO poll (id, uid, title, open, description) "
        + "VALUES (?, ?, ?, ?, ?)",
        [
            (1, 10, "a", 1, "desc"),
            (2, 11, "b", 0, ""),
        ],
    )
    conn.commit()
    return conn


def _legacy_counter_db(path: Path) -> sqlite3.Connection:
    """Legacy aggregate counters: mid 1 has 3 real presses, mid 2 one."""
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_COUNTER_DDL)
    conn.execute(_LEGACY_BAKA_DDL)
    conn.execute("INSERT INTO counter (mid, count) VALUES (1, 5)")
    conn.execute("INSERT INTO counter (mid, count) VALUES (2, 1)")
    conn.executemany(
        "INSERT INTO counter_baka (mid, uid, name, updated_at) "
        + "VALUES (?, ?, ?, ?)",
        [
            (1, 100, "a", "2026-01-01T00:00:00+00:00"),
            (1, 101, "b", "2026-01-02T00:00:00+00:00"),
            (1, 102, "c", "2026-01-03T00:00:00+00:00"),
        ],
    )
    conn.commit()
    return conn


# -- registry ---------------------------------------------------------------


def test_registry_is_ordered_and_ids_unique() -> None:
    ids = [m.id for m in MIGRATIONS]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    assert ids == [
        "001_poll_cid",
        "002_counter_events",
        "003_frog_species",
        "004_asset_kind",
        "005_frog_species_key",
    ]


def test_registry_all_gates_safe_on_fresh_db(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "fresh.db")
    try:
        for m in MIGRATIONS:
            assert m.needs(conn) is False
    finally:
        conn.close()


# -- run_one (dry run / commit / backup / no-op contract) --------------------


def test_run_one_dry_run_does_not_mutate(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "legacy.db"
    conn = _legacy_poll_db(db_path)
    try:
        rc = run_one(
            POLL_MIGRATION,
            conn,
            commit=False,
            backup_dir=str(tmp_path / "backups"),
            db_path=db_path,
        )
        assert rc == 0
        assert "dry run" in capsys.readouterr().out
        columns = {r[1] for r in conn.execute("PRAGMA table_info(poll)")}
        assert "cid" not in columns
        assert not list((tmp_path / "backups").glob("*.db"))
    finally:
        conn.close()


def test_run_one_commit_backs_up_applies_and_noops(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "legacy.db"
    backup_dir = tmp_path / "backups"
    conn = _legacy_poll_db(db_path)
    try:
        rc = run_one(
            POLL_MIGRATION,
            conn,
            commit=True,
            backup_dir=str(backup_dir),
            db_path=db_path,
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "backed up to" in out and "applied" in out

        columns = {r[1] for r in conn.execute("PRAGMA table_info(poll)")}
        assert "cid" in columns
        backups = list(backup_dir.glob("001_poll_cid_backup-*.db"))
        assert len(backups) == 1
        # the backup is a real copy of the legacy shape
        saved = sqlite3.connect(backups[0])
        try:
            saved_cols = {
                r[1] for r in saved.execute("PRAGMA table_info(poll)")
            }
            assert "cid" not in saved_cols
        finally:
            saved.close()

        # re-run: no-op, and no second backup
        rc = run_one(
            POLL_MIGRATION,
            conn,
            commit=True,
            backup_dir=str(backup_dir),
            db_path=db_path,
        )
        assert rc == 0
        assert "nothing to do" in capsys.readouterr().out
        assert len(list(backup_dir.glob("001_poll_cid_backup-*.db"))) == 1
    finally:
        conn.close()


# -- scripts/migrate.py CLI --------------------------------------------------


def test_cli_list(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "legacy.db"
    conn = _legacy_poll_db(db_path)
    conn.close()

    monkeypatch.setattr(
        "sys.argv", ["migrate.py", "--db", str(db_path), "--list"]
    )
    assert runner.main() == 0

    out = capsys.readouterr().out
    assert "001_poll_cid" in out and "pending" in out
    assert (
        "004_asset_kind" in out and "ok (applied or never needed)" in out
    )


def test_cli_only_commit_applies_one(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "legacy.db"
    conn = _legacy_poll_db(db_path)
    conn.close()

    monkeypatch.setattr(
        "sys.argv",
        [
            "migrate.py",
            "--db",
            str(db_path),
            "--only",
            "001_poll_cid",
            "--commit",
            "--backup-dir",
            str(tmp_path / "backups"),
        ],
    )
    assert runner.main() == 0
    assert "applied" in capsys.readouterr().out

    conn = sqlite3.connect(db_path)
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(poll)")}
        assert "cid" in columns
    finally:
        conn.close()


def test_cli_only_no_match_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "legacy.db"
    conn = _legacy_poll_db(db_path)
    conn.close()

    monkeypatch.setattr(
        "sys.argv", ["migrate.py", "--db", str(db_path), "--only", "nope"]
    )
    assert runner.main() == 1
    assert "no migrations match" in capsys.readouterr().out


# -- counter-events module (port coverage) -----------------------------------


def test_counter_events_plan_and_migrate(tmp_path: Path) -> None:
    conn = _legacy_counter_db(tmp_path / "legacy.db")
    try:
        assert counter_needs_migration(conn) is True
        report = counter_plan(conn)
        assert report.counters == 2
        assert report.total_events == 6  # 5 + 1

        did = migrate_counter_events(conn)
        assert did.total_events == 6

        # real presses carried over; the rest backfilled anonymously
        rows = conn.execute(
            "SELECT counter_id, uid, name, updated_at "
            + "FROM counter_event ORDER BY counter_id, uid"
        ).fetchall()
        assert len(rows) == 6
        named = [r for r in rows if r[2] is not None]
        assert len(named) == 3
        anon = [r for r in rows if r[2] is None]
        assert all(r[3] == EPOCH for r in anon)

        # derived totals match the legacy counts exactly (per-mid verify)
        totals = dict(
            conn.execute(
                "SELECT c.mid, COUNT(e.id) "
                + "FROM counter c LEFT JOIN counter_event e "
                + "ON e.counter_id = c.id GROUP BY c.id"
            ).fetchall()
        )
        assert totals == {1: 5, 2: 1}
        assert counter_needs_migration(conn) is False
    finally:
        conn.close()


def test_counter_events_needs_false_on_new_and_mid_only_shapes(
    tmp_path: Path,
) -> None:
    fresh = sqlite3.connect(tmp_path / "fresh.db")
    try:
        assert counter_needs_migration(fresh) is False
    finally:
        fresh.close()

    mid_only = sqlite3.connect(tmp_path / "mid_only.db")
    try:
        mid_only.execute("CREATE TABLE counter (mid INTEGER PRIMARY KEY)")
        mid_only.commit()
        assert counter_needs_migration(mid_only) is False
    finally:
        mid_only.close()
