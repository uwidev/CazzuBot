"""Handle the database for per-guild global frog settings."""

import logging
from enum import Enum

from asyncpg import Pool, Record, exceptions
from discord.ext import commands

from . import guild, table, utility


_log = logging.getLogger(__name__)


@utility.fkey_gid
async def add(pool: Pool, payload: table.Frog) -> None:
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO frog (gid)
                VALUES ($1)
                """,
                *payload
            )


@utility.fkey_gid
async def init(pool: Pool, gid: int, *args, **kwargs) -> None:
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO frog (gid)
                VALUES ($1)
                """,
                gid,
            )


@utility.fkey_gid
async def set_message(pool: Pool, gid: int, json_d: dict):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO frog (gid, message)
                VALUES($1, $2)
                ON CONFLICT (gid) DO UPDATE SET
                    message = EXCLUDED.message
                """,
                gid,
                json_d,
            )


@utility.fkey_gid
async def set_enabled(pool: Pool, gid: int, val: bool):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO frog (gid, enabled)
                VALUES($1, $2)
                ON CONFLICT (gid) DO UPDATE SET
                    enabled = EXCLUDED.enabled
                """,
                gid,
                val,
            )


@utility.retry(on_none=init)
async def get_message(pool: Pool, gid: int) -> list[Record]:
    async with pool.acquire() as con:
        return await con.fetchval(
            """
            SELECT message
            FROM frog
            WHERE gid = $1
            """,
            gid,
        )


@utility.retry(on_none=init)
async def get_enabled(pool: Pool, gid: int) -> list[Record]:
    """Return if frog spawns are enabled."""
    async with pool.acquire() as con:
        return await con.fetchval(
            """
            SELECT enabled
            FROM frog
            WHERE gid = $1
            """,
            gid,
        )
