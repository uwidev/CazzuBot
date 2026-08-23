"""Asset kind rename — stored ``'species'`` -> ``'image'`` migration.

Builds a temp DB with a legacy ``'species'`` asset row, runs the rename
logic directly (no CLI), and asserts the new shape — including the boot
blocker it fixes: every stored kind must coerce to the current
``AssetKind`` enum (``cazzubot.db._coerce_field`` raises on a stale
value).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cazzubot.assets import AssetKind
from scripts.migrations.asset_kind import migrate, needs_renaming, plan

_ASSET_DDL = """
CREATE TABLE asset (
    key    TEXT PRIMARY KEY,
    kind   TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    path   TEXT NOT NULL,
    url    TEXT
)
"""


def _legacy_kind_conn(path: Path) -> sqlite3.Connection:
    """An asset registry with one legacy ``'species'`` row."""
    conn = sqlite3.connect(path)
    conn.execute(_ASSET_DDL)
    conn.executemany(
        "INSERT INTO asset (key, kind, sha256, path, url) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (
                "FrogAsset.CATCH_BANNER",
                "species",
                "abc",
                "frogs/assets/caught.png",
                "https://cdn.example.com/1.png",
            ),
            (
                "FrogAsset.FROG_BASIC",
                "emoji",
                "def",
                "frogs/assets/frog_basic.png",
                None,
            ),
        ],
    )
    conn.commit()
    return conn


def test_needs_renaming_and_plan(tmp_path: Path) -> None:
    conn = _legacy_kind_conn(tmp_path / "legacy.db")
    try:
        assert needs_renaming(conn) is True
        assert plan(conn).rows == 1
    finally:
        conn.close()


def test_needs_renaming_false_when_clean(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "clean.db")
    try:
        conn.execute(_ASSET_DDL)
        conn.execute(
            "INSERT INTO asset (key, kind, sha256, path) "
            "VALUES ('FrogAsset.FROG_BASIC', 'image', '', "
            "'frogs/assets/frog_basic.png')"
        )
        conn.commit()
        assert needs_renaming(conn) is False
    finally:
        conn.close()


def test_needs_renaming_false_without_asset_table(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "fresh.db")
    try:
        assert needs_renaming(conn) is False
    finally:
        conn.close()


def test_migrate_rekeys_kind_and_is_idempotent(tmp_path: Path) -> None:
    conn = _legacy_kind_conn(tmp_path / "legacy.db")
    try:
        did = migrate(conn)
        assert did.rows == 1

        kinds = {
            r[0] for r in conn.execute("SELECT DISTINCT kind FROM asset")
        }
        assert kinds == {"image", "emoji"}
        # every stored kind coerces to the current enum — the boot blocker
        for (kind,) in conn.execute("SELECT DISTINCT kind FROM asset"):
            AssetKind(kind)
        assert needs_renaming(conn) is False
        assert plan(conn).rows == 0  # idempotent
        # published references untouched by the in-place kind rename
        url = conn.execute(
            "SELECT url FROM asset WHERE key = 'FrogAsset.CATCH_BANNER'"
        ).fetchone()[0]
        assert url == "https://cdn.example.com/1.png"
    finally:
        conn.close()
