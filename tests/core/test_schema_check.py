"""Schema checker (``scripts/schema_check.py``).

The checker exists so a forgotten migration surfaces as an exit code
instead of a boot failure. These tests build databases from the real code
DDL, mutate them into legacy shapes, and assert how each deviation is
classified (covered by a pending migration / benign disabled-plugin table
/ uncovered), that ``--simulate`` replays the pending migrations on a
copy, and that inspecting a database never writes to it.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from core.plugin import discover_plugins
from scripts.schema_check import (
    CLEAN,
    COVERED,
    CORE_SCHEMA,
    UNCOVERED,
    exit_code,
    check_db,
    main,
)

_ROOT = Path(__file__).resolve().parents[2]

_LEGACY_BOARD_DDL = """
CREATE TABLE board (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    image_url TEXT NOT NULL UNIQUE,
    msg_url   TEXT NOT NULL,
    sha256    TEXT NOT NULL
)
"""


def _all_ddl() -> list[str]:
    """Core DDL plus every plugin's (enabled or not)."""
    return CORE_SCHEMA + [
        statement
        for plugin in discover_plugins(str(_ROOT / "plugins"))
        for statement in plugin.schema
    ]


def _full_db(path: Path) -> None:
    """A database matching the code DDL exactly (no drift)."""
    conn = sqlite3.connect(path)
    try:
        for statement in _all_ddl():
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _exec(path: Path, *statements: str) -> None:
    """Run raw SQL against ``path`` (test setup)."""
    conn = sqlite3.connect(path)
    try:
        for statement in statements:
            conn.execute(statement)
        conn.commit()
    finally:
        conn.close()


def _legacy_board_db(path: Path) -> None:
    """Full DDL, then the pre-board-v2 shape (both board migrations pending)."""
    _full_db(path)
    _exec(
        path,
        "DROP TABLE board_exclusions",
        "DROP TABLE board",
        _LEGACY_BOARD_DDL,
    )


# -- classification ---------------------------------------------------------


async def test_full_ddl_db_is_clean(tmp_path: Path) -> None:
    db = tmp_path / "clean.db"
    _full_db(db)
    report = await check_db(db)
    assert report.findings == []
    assert report.guard_problems == []
    assert report.full_problems == []
    assert report.pending == []
    assert report.extra_tables == []


async def test_legacy_board_drift_is_covered_and_guard_fails(
    tmp_path: Path,
) -> None:
    db = tmp_path / "legacy.db"
    _legacy_board_db(db)
    report = await check_db(db)
    # the boot guard refuses the legacy shape — that is the point
    assert report.guard_problems
    kinds = {finding.table: finding.kind for finding in report.findings}
    assert kinds == {"board": "covered", "board_exclusions": "covered"}
    assert report.pending == [
        "009_board_channel_scope",
        "010_board_exclusions",
    ]


async def test_missing_disabled_plugin_table_is_benign(
    tmp_path: Path,
) -> None:
    db = tmp_path / "no_modlog.db"
    _full_db(db)
    _exec(db, "DROP TABLE modlog")
    report = await check_db(db)
    (finding,) = report.findings
    assert finding.table == "modlog"
    assert finding.kind == "benign"
    assert "mod" in finding.detail
    # mod ships disabled, so its table is not a boot blocker
    assert report.guard_problems == []


async def test_uncovered_drift_is_flagged(tmp_path: Path) -> None:
    db = tmp_path / "drifted.db"
    _full_db(db)
    _exec(db, "DROP TABLE poll_item")
    report = await check_db(db)
    (finding,) = report.findings
    assert finding.table == "poll_item"
    assert finding.kind == "uncovered"
    assert report.guard_problems


# -- read-only guarantee ----------------------------------------------------


async def test_check_never_writes_to_the_database(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    _legacy_board_db(db)
    before = db.read_bytes()
    await check_db(db)
    assert db.read_bytes() == before
    sidecars = [p.name for p in tmp_path.iterdir() if p.name != db.name]
    assert sidecars == []


# -- simulate ---------------------------------------------------------------


async def test_simulate_applies_pending_migrations_to_a_copy(
    tmp_path: Path,
) -> None:
    db = tmp_path / "legacy.db"
    _legacy_board_db(db)
    report = await check_db(db, simulate=True)
    assert report.simulated == []
    conn = sqlite3.connect(db)
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(board)")
        }
    finally:
        conn.close()
    assert "channel_id" not in columns  # the original is untouched


async def test_simulate_keeps_benign_findings(tmp_path: Path) -> None:
    db = tmp_path / "no_modlog.db"
    _legacy_board_db(db)
    _exec(db, "DROP TABLE modlog")
    report = await check_db(db, simulate=True)
    assert report.simulated is not None
    assert [f.table for f in report.simulated] == ["modlog"]
    assert report.simulated[0].kind == "benign"


async def test_failed_simulate_is_not_reported_as_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "legacy.db"
    _legacy_board_db(db)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("no backup for you")

    monkeypatch.setattr("scripts.schema_check.run_one", boom)
    report = await check_db(db, simulate=True)
    assert report.simulate_failed is True
    assert report.simulated is None
    assert any("simulate failed" in w for w in report.warnings)
    assert exit_code(report) == UNCOVERED


# -- CLI --------------------------------------------------------------------


def test_cli_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean = tmp_path / "clean.db"
    _full_db(clean)
    assert main([str(clean)]) == CLEAN
    assert "no drift" in capsys.readouterr().out

    legacy = tmp_path / "legacy.db"
    _legacy_board_db(legacy)
    assert main([str(legacy)]) == COVERED
    assert "scripts/migrate.py" in capsys.readouterr().out

    drifted = tmp_path / "drifted.db"
    _full_db(drifted)
    _exec(drifted, "DROP TABLE poll_item")
    assert main([str(drifted)]) == UNCOVERED
    assert "add-a-migration" in capsys.readouterr().out

    assert main([str(tmp_path / "nope.db")]) == UNCOVERED


def test_cli_defaults_to_the_dev_db(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    _full_db(tmp_path / "data" / "cazzubot-dev.db")
    assert main([]) == CLEAN
    assert "data/cazzubot-dev.db" in capsys.readouterr().out
