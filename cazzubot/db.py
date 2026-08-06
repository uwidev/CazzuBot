"""SQLite data layer.

Thin async wrapper over aiosqlite: one connection, WAL mode, foreign keys
enabled, explicit transactions guarded by an asyncio lock. Timestamps are
ISO-8601 strings, dicts/lists are JSON text, enums are their ``.value``.
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, TypeVar

import aiosqlite

_T = TypeVar("_T")

_log = logging.getLogger(__name__)


class Database:
    """Owns the sqlite connection and provides query helpers."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None
        self._tx_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Open the connection and set pragmas.

        ``isolation_level=None`` puts sqlite3 in autocommit mode so every bare
        ``execute()`` persists immediately; multi-statement writes must go
        through :meth:`transaction`.
        """
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(
            self.path, isolation_level=None
        )
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        _log.info("database opened at %s", self.path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database is not connected")
        return self._conn

    # -- queries ----------------------------------------------------------

    async def execute(self, sql: str, *args: Any) -> int:
        """Run a statement, return the rowcount (0 for DDL)."""
        cur = await self.conn.execute(sql, args)
        await cur.close()
        return cur.rowcount

    async def executemany(
        self, sql: str, seq: Sequence[Sequence[Any]]
    ) -> int:
        """Run a statement once per parameter set, return total rowcount."""
        cur = await self.conn.executemany(sql, seq)
        await cur.close()
        return cur.rowcount

    async def fetchone(self, sql: str, *args: Any) -> aiosqlite.Row | None:
        cur = await self.conn.execute(sql, args)
        try:
            return await cur.fetchone()
        finally:
            await cur.close()

    async def fetchall(self, sql: str, *args: Any) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(sql, args)
        try:
            return list(await cur.fetchall())
        finally:
            await cur.close()

    async def fetchval(self, sql: str, *args: Any) -> Any:
        row = await self.fetchone(sql, *args)
        return row[0] if row else None

    async def fetch_model(
        self, model: type[_T], sql: str, *args: Any
    ) -> _T | None:
        """Fetch one row and build a dataclass model from it (see row_to)."""
        row = await self.fetchone(sql, *args)
        return row_to(model, row) if row is not None else None

    async def fetch_models(
        self, model: type[_T], sql: str, *args: Any
    ) -> list[_T]:
        """Fetch rows and build dataclass models from them (see row_to)."""
        rows = await self.fetchall(sql, *args)
        return rows_to(model, rows)

    async def execute_lastrowid(self, sql: str, *args: Any) -> int | None:
        """Run an INSERT and return the new rowid."""
        cur = await self.conn.execute(sql, args)
        await cur.close()
        return cur.lastrowid

    # -- transactions -----------------------------------------------------

    @asynccontextmanager  # pyright: ignore[reportDeprecated]  # correct on py3.10
    async def transaction(self) -> AsyncIterator[None]:
        """Explicit transaction; serialized against other transactions."""
        async with self._tx_lock:
            await self.execute("BEGIN IMMEDIATE")
            try:
                yield
                await self.execute("COMMIT")
            except BaseException:
                await self.execute("ROLLBACK")
                raise

    # -- schema -----------------------------------------------------------

    async def run_schema(self, statements: Sequence[str]) -> None:
        """Execute idempotent DDL statements (``CREATE TABLE IF NOT EXISTS``…)."""
        async with self.transaction():
            for statement in statements:
                await self.conn.execute(statement)
            await self.conn.execute("PRAGMA user_version = 1")
        _log.info("schema applied (%d statements)", len(statements))


# -- helpers for (de)serializing values ---------------------------------


def row_to(model: type[_T], row: aiosqlite.Row) -> _T:
    """Build a dataclass from a row; column names must match field names.

    The constructor is the honest boundary between sqlite's dynamic rows and
    static types: a column/field mismatch raises here instead of returning a
    wrong-typed dict.
    """
    return model(**{k: row[k] for k in row.keys()})


def rows_to(model: type[_T], rows: Sequence[aiosqlite.Row]) -> list[_T]:
    """Build dataclasses from rows (see :func:`row_to`)."""
    return [row_to(model, r) for r in rows]


def dump_json(value: Any) -> str:
    """Serialize a value for a TEXT column."""
    return json.dumps(value, default=str)


def load_json(raw: str | None, default: Any = None) -> Any:
    """Deserialize a value from a TEXT column."""
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw
