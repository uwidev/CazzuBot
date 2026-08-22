"""Schema drift guard + model-boundary coercion.

Ported from scripts/functest.py (schema half); the coercion half pins the
``row_to``/``rows_to`` behavior every typed fetch builds on.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import pendulum
import pytest
from typing import Any

from cazzubot import CazzuBot, Config
from cazzubot.db import Database, SchemaMismatchError, _coerce_field  # pyright: ignore[reportPrivateUsage]
from plugins.experience import db as exp_db
from tests.conftest import _DUMMY_TOKEN


class _Color(Enum):
    """A tiny stored-as-value enum for coercion tests."""

    RED = "red"
    BLUE = "blue"


@dataclass(slots=True)
class _Sample:
    """One row of every stored shape the boundary can coerce."""

    name: str
    count: int
    expires: pendulum.DateTime | None
    stamped: pendulum.DateTime
    color: _Color
    meta: dict[str, Any]
    tags: list[str]
    flag: bool


@dataclass(slots=True)
class _Narrow:
    """A projection subset (fewer columns than a full row)."""

    name: str
    count: int


async def _sample_db(tmp_path: Path) -> Database:
    """A temp Database with one table storing every raw shape."""
    db = Database(str(tmp_path / "coerce.db"))
    await db.connect()
    await db.execute(
        """
        CREATE TABLE sample (
            name     TEXT NOT NULL,
            count    INTEGER NOT NULL,
            expires  TEXT,
            stamped  TEXT NOT NULL,
            color    TEXT NOT NULL,
            meta     TEXT NOT NULL,
            tags     TEXT NOT NULL,
            flag     INTEGER NOT NULL
        )
        """
    )
    return db


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
    import hikari

    drift_path = tmp_path / "drift.db"
    _make_drift_db(drift_path)
    drift_bot = CazzuBot(
        Config(
            token=_DUMMY_TOKEN,
            owner_id=1,
            guild_id=2,
            db_path=str(drift_path),
        )
    )
    try:
        with pytest.raises(SystemExit):
            await drift_bot._on_starting(  # pyright: ignore[reportPrivateUsage]
                hikari.StartingEvent(app=drift_bot)
            )
    finally:
        # the guard aborts before the scheduler/plugin hooks run — only the
        # open db connection needs closing.
        await drift_bot.db.close()


# -- model-boundary coercion (row_to/rows_to) -------------------------------


async def test_fetch_model_coerces_every_stored_shape(
    tmp_path: Path,
) -> None:
    """Stored TEXT/INTEGER come back as the dataclass's declared types."""
    db = await _sample_db(tmp_path)
    try:
        stamped = pendulum.datetime(2026, 8, 20, 13, 30, tz="UTC")
        await db.execute(
            """
            INSERT INTO sample
                (name, count, expires, stamped, color, meta, tags, flag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            "leaf",
            3,
            stamped.isoformat(),
            stamped.isoformat(),
            _Color.RED.value,
            '{"a": 1}',
            "[1, 2]",
            1,
        )
        row = await db.fetch_model(
            _Sample, "SELECT * FROM sample WHERE name = ?", "leaf"
        )
        assert row is not None
        assert (row.name, row.count) == ("leaf", 3)
        assert row.expires == stamped  # TEXT ISO -> DateTime
        assert row.stamped == stamped  # non-None variant
        assert row.color is _Color.RED  # TEXT .value -> Enum
        assert row.meta == {"a": 1}  # TEXT JSON -> dict
        assert row.tags == [1, 2]  # TEXT JSON -> list
        assert row.flag is True  # INTEGER 0/1 -> bool

        # NULL-aware: the union field reads None, the others stay typed
        await db.execute(
            "UPDATE sample SET expires = NULL WHERE name = ?", "leaf"
        )
        null_row = await db.fetch_model(
            _Sample, "SELECT * FROM sample WHERE name = ?", "leaf"
        )
        assert null_row is not None and null_row.expires is None
    finally:
        await db.close()


async def test_fetch_model_narrow_projection(tmp_path: Path) -> None:
    """A subset SELECT still maps — the model need not see every column."""
    db = await _sample_db(tmp_path)
    try:
        await db.execute(
            """
            INSERT INTO sample
                (name, count, expires, stamped, color, meta, tags, flag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            "narrow",
            7,
            None,
            pendulum.now("UTC").isoformat(),
            _Color.BLUE.value,
            "{}",
            "[]",
            0,
        )
        row = await db.fetch_model(
            _Narrow,
            "SELECT name, count FROM sample WHERE name = ?",
            "narrow",
        )
        assert row == _Narrow(name="narrow", count=7)
    finally:
        await db.close()


async def test_fetch_models_coerces_every_row(tmp_path: Path) -> None:
    """rows_to follows the same coercion path as row_to."""
    db = await _sample_db(tmp_path)
    try:
        stamped = pendulum.now("UTC")
        for name in ("a", "b"):
            await db.execute(
                """
                INSERT INTO sample
                    (name, count, expires, stamped, color, meta, tags, flag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                name,
                1,
                None,
                stamped.isoformat(),
                _Color.BLUE.value,
                "{}",
                "[]",
                0,
            )
        rows = await db.fetch_models(_Sample, "SELECT * FROM sample")
        assert len(rows) == 2
        assert all(r.stamped == stamped for r in rows)
    finally:
        await db.close()


async def test_uncoercible_value_raises_named_boundary_error(
    tmp_path: Path,
) -> None:
    """A stored value that can't be a field's type raises with the column."""
    db = await _sample_db(tmp_path)
    try:
        await db.execute(
            """
            INSERT INTO sample
                (name, count, expires, stamped, color, meta, tags, flag)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            "bad",
            1,
            "not-a-timestamp",
            pendulum.now("UTC").isoformat(),
            _Color.RED.value,
            "{}",
            "[]",
            0,
        )
        with pytest.raises(TypeError, match="expires"):
            await db.fetch_model(_Sample, "SELECT * FROM sample")
    finally:
        await db.close()


def test_coerce_field_already_typed_passes_through() -> None:
    """Coercion is idempotent — a DateTime in a DateTime field stays put."""
    now = pendulum.now("UTC")
    assert _coerce_field(pendulum.DateTime, now) is now
    assert _coerce_field(_Color, _Color.RED) is _Color.RED
    assert _coerce_field(bool, True) is True


def test_coerce_field_none_stays_none() -> None:
    """None never coerces — it means the column was NULL."""
    assert _coerce_field(pendulum.DateTime | None, None) is None
    assert _coerce_field(dict[str, Any], None) is None
