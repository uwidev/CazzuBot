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


class SchemaMismatchError(Exception):
    """Raised when the on-disk sqlite schema differs from the DDL."""


class Database:
    """Owns the sqlite connection and provides query helpers."""

    def __init__(self, path: str) -> None:
        """Hold the database ``path``; the connection opens in :meth:`connect`.

        Also owns the asyncio lock that serializes explicit transactions.
        """
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
        """Close the connection (no-op if never opened)."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @property
    def conn(self) -> aiosqlite.Connection:
        """The live connection used by the query helpers.

        Raises:
            RuntimeError: if the database is not connected.
        """
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
        """Run a statement and return the first row, or ``None``."""
        cur = await self.conn.execute(sql, args)
        try:
            return await cur.fetchone()
        finally:
            await cur.close()

    async def fetchall(self, sql: str, *args: Any) -> list[aiosqlite.Row]:
        """Run a statement and return all rows as a list."""
        cur = await self.conn.execute(sql, args)
        try:
            return list(await cur.fetchall())
        finally:
            await cur.close()

    async def fetchval(self, sql: str, *args: Any) -> Any:
        """Run a statement and return the first column of the first row, or ``None``."""
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
        _log.info("schema applied (%d statements)", len(statements))

    async def verify_schema(self, statements: Sequence[str]) -> None:
        """Check the on-disk schema matches the Python-defined DDL exactly.

        Every table the DDL statements create must exist in the database with
        identical columns, constraints and indexes; tables that only exist in
        the database are allowed. Raises :class:`SchemaMismatchError` listing
        every difference — the caller decides how to fail.
        """
        ref = await aiosqlite.connect(":memory:")
        ref.row_factory = aiosqlite.Row
        try:
            for statement in statements:
                await ref.execute(statement)
            problems = await _schema_diff(self.conn, ref)
        finally:
            await ref.close()
        if problems:
            detail = "\n".join(f"  - {p}" for p in problems)
            raise SchemaMismatchError(
                "database schema does not match the Python-defined "
                + f"schema ({self.path}):\n{detail}"
            )


# -- schema comparison helpers --------------------------------------------


def _quote(name: str) -> str:
    """Quote an identifier for use inside a PRAGMA statement."""
    return '"' + name.replace('"', '""') + '"'


async def _table_names(conn: aiosqlite.Connection) -> set[str]:
    """Names of user tables (sqlite-internal tables excluded)."""
    rows = await conn.execute_fetchall(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )
    return {r["name"] for r in rows if not r["name"].startswith("sqlite_")}


async def _columns(
    conn: aiosqlite.Connection, table: str
) -> tuple[tuple[Any, ...], ...]:
    """PRAGMA table_info rows: (name, type, notnull, default, pk position)."""
    rows = await conn.execute_fetchall(
        f"PRAGMA table_info({_quote(table)})"
    )
    return tuple(
        (r["name"], r["type"], r["notnull"], r["dflt_value"], r["pk"])
        for r in rows
    )


async def _indexes(
    conn: aiosqlite.Connection, table: str
) -> frozenset[tuple[Any, ...]]:
    """Indexes (incl. sqlite's automatic PK/UNIQUE ones) with column lists."""
    out: set[tuple[Any, ...]] = set()
    rows = await conn.execute_fetchall(
        f"PRAGMA index_list({_quote(table)})"
    )
    for row in rows:
        cols = tuple(
            (c["seqno"], c["name"] if c["name"] is not None else c["cid"])
            for c in await conn.execute_fetchall(
                f"PRAGMA index_info({_quote(row['name'])})"
            )
        )
        out.add(
            (
                row["name"],
                row["unique"],
                row["origin"],
                row["partial"],
                cols,
            )
        )
    return frozenset(out)


async def _foreign_keys(
    conn: aiosqlite.Connection, table: str
) -> tuple[tuple[Any, ...], ...]:
    """PRAGMA foreign_key_list rows (id, seq, table, from, to, actions)."""
    rows = await conn.execute_fetchall(
        f"PRAGMA foreign_key_list({_quote(table)})"
    )
    return tuple(
        (
            r["id"],
            r["seq"],
            r["table"],
            r["from"],
            r["to"],
            r["on_update"],
            r["on_delete"],
            r["match"],
        )
        for r in rows
    )


async def _has_sql_keyword(
    conn: aiosqlite.Connection, table: str, keyword: str
) -> bool:
    """Whether the stored CREATE TABLE text contains a keyword (e.g.
    AUTOINCREMENT) that PRAGMA introspection cannot see."""
    rows = list(
        await conn.execute_fetchall(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        )
    )
    return bool(rows and keyword in (rows[0]["sql"] or "").upper())


async def _schema_diff(
    actual: aiosqlite.Connection, expected: aiosqlite.Connection
) -> list[str]:
    """Human-readable differences between the real and the DDL-defined schema.

    Extra tables in ``actual`` are ignored; every expected table must exist
    with exactly matching columns, indexes, foreign keys and rowid keywords.
    """
    want_tables = await _table_names(expected)
    got_tables = await _table_names(actual)
    problems: list[str] = []
    for table in sorted(want_tables):
        if table not in got_tables:
            problems.append(
                f"table {table!r} is missing from the database"
            )
            continue
        want = await _columns(expected, table)
        got = await _columns(actual, table)
        if want != got:
            problems.append(
                f"""table {table!r}: columns differ
    expected: {want}
    actual:   {got}"""
            )
        want = await _indexes(expected, table)
        got = await _indexes(actual, table)
        if want != got:
            problems.append(
                f"""table {table!r}: indexes differ
    expected: {sorted(want)}
    actual:   {sorted(got)}"""
            )
        want = await _foreign_keys(expected, table)
        got = await _foreign_keys(actual, table)
        if want != got:
            problems.append(
                f"""table {table!r}: foreign keys differ
    expected: {want}
    actual:   {got}"""
            )
        for keyword in ("AUTOINCREMENT", "WITHOUT ROWID"):
            want = await _has_sql_keyword(expected, table, keyword)
            got = await _has_sql_keyword(actual, table, keyword)
            if want != got:
                problems.append(
                    f"table {table!r}: {keyword} expected={want} actual={got}"
                )
    return problems


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
    """Deserialize a value from a TEXT column.

    Unparseable text is returned verbatim (settings tolerate legacy
    plain-string values); ``None`` yields ``default``.
    """
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw
