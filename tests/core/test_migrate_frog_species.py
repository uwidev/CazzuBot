"""Frog species migration (ROADMAP Phase 3) — legacy columns → inventory.

Builds a temp DB in the legacy shape (``member_frog.normal/frozen`` +
``member_frog_log.type`` = 'normal'|'frozen'), runs the migration logic
directly (no CLI), and asserts the new shape — plus the acceptance
criterion that a migrated DB boots the new code through the real boot
schema guard.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import hikari

from cazzubot import CazzuBot, Config
from cazzubot.models import FrogState, FrogItemKey
from scripts.migrations.frog_species import (
    DEFAULT_SPECIES_KEY,
    migrate,
    needs_migration,
    plan,
)
from tests.conftest import _DUMMY_TOKEN

_LEGACY_MEMBER_FROG = """
CREATE TABLE member_frog (
    uid     INTEGER PRIMARY KEY,
    normal  INTEGER NOT NULL DEFAULT 0,
    frozen  INTEGER NOT NULL DEFAULT 0,
    capture INTEGER NOT NULL DEFAULT 0
)
"""

_LEGACY_LOG = """
CREATE TABLE member_frog_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        INTEGER NOT NULL,
    type       TEXT NOT NULL DEFAULT 'normal',
    at         TEXT NOT NULL,
    waited_for REAL
)
"""


def _legacy_conn(path: Path) -> sqlite3.Connection:
    """A legacy-shape DB: uids 1 (3 normal + 2 frozen), 2 (1 frozen),
    3 (zero qty) and three capture logs ('normal'/'frozen'/'normal')."""
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_MEMBER_FROG)
    conn.execute(_LEGACY_LOG)
    for uid, normal, frozen, capture in (
        (1, 3, 2, 5),
        (2, 0, 1, 4),
        (3, 0, 0, 0),
    ):
        conn.execute(
            "INSERT INTO member_frog (uid, normal, frozen, capture) "
            "VALUES (?, ?, ?, ?)",
            (uid, normal, frozen, capture),
        )
    for uid, kind, at in (
        (1, "normal", "2026-01-01T00:00:00+00:00"),
        (1, "frozen", "2026-01-02T00:00:00+00:00"),
        (2, "normal", "2026-01-03T00:00:00+00:00"),
    ):
        conn.execute(
            "INSERT INTO member_frog_log (uid, type, at, waited_for) "
            "VALUES (?, ?, ?, 1.5)",
            (uid, kind, at),
        )
    conn.commit()
    return conn


def test_plan_reports_exact_counts(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        assert needs_migration(conn) is True
        report = plan(conn)
        assert report.members == 2  # uids 1 and 2 hold quantities
        assert report.inventory_rows == 3  # 1 normal + 1 frozen + 1 frozen
        assert report.log_rows == 3
    finally:
        conn.close()


def test_migrate_folds_into_default_species(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        report = migrate(conn)
        assert report.members == 2 and report.inventory_rows == 3

        rows = conn.execute(
            "SELECT uid, item, qty FROM inventory ORDER BY uid, item"
        ).fetchall()
        assert rows == [
            (1, "frog:basic:frozen", 2),
            (1, "frog:basic:normal", 3),
            (2, "frog:basic:frozen", 1),
        ], rows
        # member_frog keeps only the lifetime capture counter
        columns = {
            r[1] for r in conn.execute("PRAGMA table_info(member_frog)")
        }
        assert columns == {"uid", "capture"}
        assert (
            conn.execute(
                "SELECT capture FROM member_frog WHERE uid = 1"
            ).fetchone()[0]
            == 5
        )
        # log types rewritten to the species key
        types = [
            r[0]
            for r in conn.execute(
                "SELECT type FROM member_frog_log ORDER BY id"
            )
        ]
        assert types == [DEFAULT_SPECIES_KEY] * 3
        # the rebuilt log table carries the NEW default (schema guard)
        info = conn.execute(
            "PRAGMA table_info(member_frog_log)"
        ).fetchall()
        type_default = next(r for r in info if r[1] == "type")
        assert type_default[4] == "'basic'"
        assert needs_migration(conn) is False
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        migrate(conn)
        # the idempotence gate: the legacy shape is gone, so a second run
        # is a no-op (and plan's legacy-column queries are never reached)
        assert needs_migration(conn) is False
    finally:
        conn.close()


def test_needs_migration_false_without_legacy_shape(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(tmp_path / "fresh.db")
    try:
        assert needs_migration(conn) is False  # no tables at all
    finally:
        conn.close()


async def test_migrated_db_boots_new_code(tmp_path: Path) -> None:
    """Acceptance: a migrated legacy DB passes the boot schema guard."""
    db_path = tmp_path / "migrated.db"
    conn = _legacy_conn(db_path)
    try:
        migrate(conn)
    finally:
        conn.close()

    instance = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(db_path),
        ),
        plugins_dir="plugins",
    )
    try:
        # _on_starting runs run_schema + verify_schema + on_load hooks;
        # a leftover legacy shape would SystemExit here
        await instance._on_starting(  # pyright: ignore[reportPrivateUsage]
            hikari.StartingEvent(app=instance)
        )
        # the new code reads the migrated inventory
        from plugins.frogs import db as frog_db

        assert (
            await frog_db.get_inventory(
                instance.db, 1, FrogItemKey.BASIC, FrogState.NORMAL
            )
            == 3
        )
        assert (
            await frog_db.get_inventory(
                instance.db, 2, FrogItemKey.BASIC, FrogState.FROZEN
            )
            == 1
        )
    finally:
        await instance._on_stopping(  # pyright: ignore[reportPrivateUsage]
            hikari.StoppingEvent(app=instance)
        )
