"""Asset message-id migration — legacy ``asset`` rows (url only) → the
``message_id`` column the boot verification needs to find the publication.

Builds a temp DB in the legacy shape, runs the migration logic directly
(no CLI), and asserts the new shape — plus the acceptance criterion that a
migrated DB passes the real boot schema guard for the assets DDL.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from core.assets import SCHEMA
from core.db import Database
from scripts.migrations.asset_message_id import (
    migrate,
    needs_migration,
    plan,
)

_LEGACY_ASSET = """
CREATE TABLE asset (
    key    TEXT PRIMARY KEY,
    kind   TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    path   TEXT NOT NULL,
    url    TEXT
)
"""

# (key, kind, sha256, path, url) — one published media row, one emoji row
_LEGACY_ROWS = [
    (
        "FrogAsset.CATCH_BANNER",
        "image",
        "85c75a0e",
        "frogs/assets/caught.png",
        "https://cdn.discordapp.com/attachments/1/2/caught.png?ex=0",
    ),
    (
        "FrogAsset.FROG_BASIC",
        "emoji",
        "c60f8002",
        "frogs/assets/frog-basic.png",
        "<:frog_basic:1542221935948206150>",
    ),
]


def _legacy_conn(path: Path) -> sqlite3.Connection:
    """A legacy-shape DB: an asset table without the message_id column."""
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_ASSET)
    conn.executemany(
        "INSERT INTO asset (key, kind, sha256, path, url) "
        "VALUES (?, ?, ?, ?, ?)",
        _LEGACY_ROWS,
    )
    conn.commit()
    return conn


def test_migrate_adds_message_id_and_keeps_rows(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        report = plan(conn)  # dry-run report must not mutate
        assert report.rows == 1  # the published media row
        assert needs_migration(conn) is True
        migrate(conn)

        assert needs_migration(conn) is False
        cols = {r[1] for r in conn.execute("PRAGMA table_info(asset)")}
        assert "message_id" in cols
        rows = conn.execute(
            "SELECT key, kind, url, message_id FROM asset ORDER BY key"
        ).fetchall()
        # references survive; the id is unknown until the boot discovers it
        assert rows == [
            (
                "FrogAsset.CATCH_BANNER",
                "image",
                _LEGACY_ROWS[0][4],
                None,
            ),
            ("FrogAsset.FROG_BASIC", "emoji", _LEGACY_ROWS[1][4], None),
        ]
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        migrate(conn)
        # the idempotence gate: the column exists, so the runner would skip
        # a second run entirely
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


async def test_migrated_db_passes_schema_guard(tmp_path: Path) -> None:
    """Acceptance: the migrated shape matches the boot guard's DDL exactly
    (column order included — ALTER TABLE appends)."""
    db_path = tmp_path / "migrated.db"
    conn = _legacy_conn(db_path)
    try:
        migrate(conn)
    finally:
        conn.close()

    db = Database(str(db_path))
    await db.connect()
    try:
        # the boot guard would SystemExit on a schema mismatch — this
        # raises SchemaMismatchError instead, so a clean pass is proof
        await db.verify_schema(SCHEMA)
    finally:
        await db.close()
