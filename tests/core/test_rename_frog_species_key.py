"""Frog species key rename — legacy ``leaf_frog`` -> ``basic`` migration.

Builds a temp DB in the current shape but with the legacy key values
(``frog:leaf_frog:*`` inventory stacks + ``'leaf_frog'`` log types and
default), runs the rename logic directly (no CLI), and asserts the new
shape — plus the acceptance criterion that the renamed DB boots the new
code through the real boot schema guard.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import hikari

from cazzubot import CazzuBot, Config
from cazzubot.models import FrogState, FrogItemKey
from scripts.rename_frog_species_key import (
    INVENTORY_DDL,
    migrate,
    needs_renaming,
    plan,
)
from tests.conftest import _DUMMY_TOKEN

_MEMBER_FROG_DDL = """
CREATE TABLE member_frog (
    uid     INTEGER PRIMARY KEY,
    capture INTEGER NOT NULL DEFAULT 0
)
"""

_LEGACY_LOG = """
CREATE TABLE member_frog_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        INTEGER NOT NULL,
    type       TEXT NOT NULL DEFAULT 'leaf_frog',
    at         TEXT NOT NULL,
    waited_for REAL
)
"""

_CURRENT_LOG = """
CREATE TABLE member_frog_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    uid        INTEGER NOT NULL,
    type       TEXT NOT NULL DEFAULT 'basic',
    at         TEXT NOT NULL,
    waited_for REAL
)
"""


def _legacy_keyed_conn(path: Path) -> sqlite3.Connection:
    """A current-shape DB still holding the legacy key values."""
    conn = sqlite3.connect(path)
    conn.execute(INVENTORY_DDL)
    conn.execute(_MEMBER_FROG_DDL)
    conn.execute(_LEGACY_LOG)
    conn.executemany(
        "INSERT INTO inventory (uid, item, qty) VALUES (?, ?, ?)",
        [
            (1, "frog:leaf_frog:normal", 3),
            (1, "frog:leaf_frog:frozen", 2),
            (2, "frog:leaf_frog:normal", 1),
        ],
    )
    conn.executemany(
        "INSERT INTO member_frog_log (uid, type, at, waited_for) "
        "VALUES (?, ?, ?, 1.5)",
        [
            (1, "leaf_frog", "2026-01-01T00:00:00+00:00"),
            (2, "leaf_frog", "2026-01-02T00:00:00+00:00"),
        ],
    )
    conn.commit()
    return conn


def test_needs_renaming_true_with_legacy_keys(tmp_path: Path) -> None:
    conn = _legacy_keyed_conn(tmp_path / "legacy.db")
    try:
        assert needs_renaming(conn) is True
        report = plan(conn)
        assert report.inventory_rows == 3
        assert report.log_rows == 2
    finally:
        conn.close()


def test_needs_renaming_false_when_clean(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "clean.db")
    try:
        conn.execute(INVENTORY_DDL)
        conn.execute(_CURRENT_LOG)
        conn.execute(
            "INSERT INTO inventory (uid, item, qty) "
            "VALUES (1, 'frog:basic:normal', 3)"
        )
        conn.commit()
        assert needs_renaming(conn) is False
    finally:
        conn.close()


def test_needs_renaming_false_without_tables(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "fresh.db")
    try:
        assert needs_renaming(conn) is False
    finally:
        conn.close()


def test_migrate_rekeys_rows_and_rebuilds_default(tmp_path: Path) -> None:
    conn = _legacy_keyed_conn(tmp_path / "legacy.db")
    try:
        did = migrate(conn)
        assert did.inventory_rows == 3 and did.log_rows == 2

        items = {r[0] for r in conn.execute("SELECT item FROM inventory")}
        assert items == {"frog:basic:normal", "frog:basic:frozen"}
        types = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT type FROM member_frog_log"
            )
        }
        assert types == {"basic"}
        # the rebuilt log table carries the NEW default (schema guard)
        info = conn.execute(
            "PRAGMA table_info(member_frog_log)"
        ).fetchall()
        type_default = next(r for r in info if r[1] == "type")
        assert type_default[4] == "'basic'"
        assert needs_renaming(conn) is False
        assert plan(conn).inventory_rows == 0  # idempotent
    finally:
        conn.close()


async def test_renamed_db_boots_new_code(tmp_path: Path) -> None:
    """Acceptance: a renamed DB passes the boot schema guard and resolves."""
    db_path = tmp_path / "renamed.db"
    conn = _legacy_keyed_conn(db_path)
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
        # a leftover legacy key/default would SystemExit here
        await instance._on_starting(  # pyright: ignore[reportPrivateUsage]
            hikari.StartingEvent(app=instance)
        )
        from plugins.frogs import db as frog_db

        assert (
            await frog_db.get_inventory(
                instance.db, 1, FrogItemKey.BASIC, FrogState.NORMAL
            )
            == 3
        )
        assert (
            await frog_db.get_inventory(
                instance.db, 1, FrogItemKey.BASIC, FrogState.FROZEN
            )
            == 2
        )
        assert (
            await frog_db.get_inventory(
                instance.db, 2, FrogItemKey.BASIC, FrogState.NORMAL
            )
            == 1
        )
    finally:
        await instance._on_stopping(  # pyright: ignore[reportPrivateUsage]
            hikari.StoppingEvent(app=instance)
        )
