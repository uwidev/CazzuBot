"""Effect-contribution migration — legacy member_effect rows → seam store.

Builds a temp DB in the legacy shape (``member_effect`` with
``EXP_MULTIPLIER`` values), runs the migration logic directly (no CLI),
and asserts the new shape — plus the acceptance criterion that a migrated
DB boots the new code through the real boot schema guard and the folded
multiplier reads back through the experience seam pull.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import hikari

from cazzubot import CazzuBot, Config
from cazzubot.effects import Scope
from scripts.migrations.effect_contributions import (
    LEGACY_SOURCE,
    migrate,
    needs_migration,
    plan,
)
from tests.conftest import _DUMMY_TOKEN

_LEGACY_MEMBER_EFFECT = """
CREATE TABLE member_effect (
    uid        INTEGER NOT NULL,
    key        TEXT NOT NULL,
    value      REAL NOT NULL,
    expires_at TEXT,
    PRIMARY KEY (uid, key)
)
"""


def _legacy_conn(path: Path) -> sqlite3.Connection:
    """A legacy-shape DB: uid 1 has a timed ×2.0 multiplier (far future
    expiry, so the new lazy expiry never prunes it), uid 2 a permanent
    ×1.5 one."""
    conn = sqlite3.connect(path)
    conn.execute(_LEGACY_MEMBER_EFFECT)
    conn.executemany(
        "INSERT INTO member_effect (uid, key, value, expires_at) "
        + "VALUES (?, ?, ?, ?)",
        (
            (1, "exp_multiplier", 2.0, "2099-02-01T00:00:00+00:00"),
            (2, "exp_multiplier", 1.5, None),
        ),
    )
    conn.commit()
    return conn


def test_plan_reports_exact_counts(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        assert needs_migration(conn) is True
        assert plan(conn).rows == 2
    finally:
        conn.close()


def test_migrate_folds_legacy_rows(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        assert migrate(conn).rows == 2

        rows = conn.execute(
            "SELECT scope_kind, scope_id, seam, source, payload, expires_at"
            + " FROM effect_contribution ORDER BY scope_id"
        ).fetchall()
        assert rows == [
            (
                "member",
                1,
                "message_exp_multiplier",
                LEGACY_SOURCE,
                json.dumps({"op": "mult", "value": 2.0}),
                "2099-02-01T00:00:00+00:00",
            ),
            (
                "member",
                2,
                "message_exp_multiplier",
                LEGACY_SOURCE,
                json.dumps({"op": "mult", "value": 1.5}),
                None,
            ),
        ], rows
        # the legacy table is dropped entirely (boot guard accepts)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert "member_effect" not in tables
        assert needs_migration(conn) is False
    finally:
        conn.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = _legacy_conn(tmp_path / "legacy.db")
    try:
        migrate(conn)
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


async def test_migrated_db_boots_and_pull_reads_multiplier(
    tmp_path: Path,
) -> None:
    """Acceptance: a migrated legacy DB boots and the seam pull sees the fold."""
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
        # _on_starting runs run_schema + verify_schema + on_load hooks; a
        # leftover legacy shape would SystemExit here
        await instance._on_starting(  # pyright: ignore[reportPrivateUsage]
            hikari.StartingEvent(app=instance)
        )
        # the new experience pull reads the folded multipliers
        from cazzubot import effects
        from plugins.experience.logic import EffectSeam

        assert (
            await effects.product(
                instance.db,
                Scope.member(1),
                EffectSeam.MESSAGE_EXP_MULTIPLIER,
            )
            == 2.0
        )
        assert (
            await effects.product(
                instance.db,
                Scope.member(2),
                EffectSeam.MESSAGE_EXP_MULTIPLIER,
            )
            == 1.5
        )
    finally:
        await instance._on_stopping(  # pyright: ignore[reportPrivateUsage]
            hikari.StoppingEvent(app=instance)
        )
