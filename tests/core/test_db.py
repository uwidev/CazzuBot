"""Schema drift guard — ported from scripts/functest.py."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from cazzubot import CazzuBot, Config
from cazzubot.db import Database, SchemaMismatchError
from plugins.experience import db as exp_db


def _make_drift_db(path: Path) -> None:
    """A DB whose member_exp columns don't match the exp DDL."""
    raw = sqlite3.connect(path)
    raw.execute(
        """
        CREATE TABLE member_exp (
            uid INTEGER PRIMARY KEY,
            lifetime INTEGER NOT NULL DEFAULT 0,
            msg_cnt INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    raw.execute(
        """
        CREATE TABLE member_exp_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            exp INTEGER NOT NULL,
            at TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'message'
        )
        """
    )
    raw.execute(
        "CREATE INDEX idx_exp_log_uid_at ON member_exp_log (uid, at)"
    )
    raw.execute("CREATE TABLE extra_thing (x TEXT)")  # extras allowed
    raw.commit()
    raw.close()


async def test_verify_schema_rejects_drift(
    tmp_path: Path,
) -> None:
    drift_path = tmp_path / "drift.db"
    _make_drift_db(drift_path)
    drift = Database(str(drift_path))
    await drift.connect()
    try:
        with pytest.raises(SchemaMismatchError):
            await drift.verify_schema(exp_db.SCHEMA)
    finally:
        await drift.close()


async def test_boot_aborts_on_schema_mismatch(tmp_path: Path) -> None:
    drift_path = tmp_path / "drift.db"
    _make_drift_db(drift_path)
    drift_bot = CazzuBot(
        Config(
            token="fake", owner_id=1, guild_id=2, db_path=str(drift_path)
        )
    )

    async def _ready() -> None:
        pass

    drift_bot.wait_until_ready = _ready  # type: ignore[method-assign]
    try:
        with pytest.raises(SystemExit):
            await drift_bot.setup_hook()
    finally:
        await drift_bot.close()
