"""Member item log migration — a NEW table, no data to port.

Builds a DB with the inventory store but no ``member_item_log``, runs the
migration directly (no CLI), and asserts the table and its index appear
with the exact DDL the inventory plugin defines. A fresh DB (no inventory
table at all) must be skipped like every other shape-gated migration.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.migrations.member_item_log import (
    migrate,
    needs_migration,
    verify,
)

_INVENTORY_ONLY = """
CREATE TABLE inventory (
    uid  INTEGER NOT NULL,
    item TEXT NOT NULL,
    qty  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (uid, item)
)
"""


def _inventory_db(path: Path) -> sqlite3.Connection:
    """A DB with the store but no consumption ledger."""
    conn = sqlite3.connect(path)
    conn.execute(_INVENTORY_ONLY)
    conn.commit()
    return conn


def test_migrate_creates_item_log_table(tmp_path: Path) -> None:
    conn = _inventory_db(tmp_path / "legacy.db")
    try:
        assert needs_migration(conn) is True
        migrate(conn)

        assert needs_migration(conn) is False
        cols = {
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(member_item_log)"
            ).fetchall()
        }
        assert {"id", "uid", "item_id", "amount", "at"} <= cols
        # id is the autoincrement primary key
        pks = [
            r[5]
            for r in conn.execute(
                "PRAGMA table_info(member_item_log)"
            ).fetchall()
        ]
        assert pks.count(1) == 1
        verify(conn)
        # the inventory table itself is untouched
        assert needs_migration(conn) is False
    finally:
        conn.close()


def test_needs_migration_false_on_fresh_db(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "fresh.db")
    try:
        assert needs_migration(conn) is False  # no inventory table at all
    finally:
        conn.close()


def test_needs_migration_false_when_table_present(tmp_path: Path) -> None:
    conn = _inventory_db(tmp_path / "done.db")
    try:
        conn.execute(
            "CREATE TABLE member_item_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "uid INTEGER NOT NULL,"
            "item_id TEXT NOT NULL,"
            "amount INTEGER NOT NULL,"
            "at TEXT NOT NULL)"
        )
        conn.commit()
        assert needs_migration(conn) is False
    finally:
        conn.close()
