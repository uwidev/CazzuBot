"""Handle frog settings."""

import logging
from enum import Enum

from asyncpg import Pool, Record, exceptions
from discord.ext import commands

from . import guild, table, utility


_log = logging.getLogger(__name__)


@utility.fkey_channel
async def add(pool: Pool, frog: table.Frog) -> None:
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO frog (gid, cid, interval, persist)
                VALUES ($1, $2, $3, $4, $5)
                """,
                *frog
            )


@utility.fkey_channel
async def upsert(pool: Pool, frog: table.Frog) -> None:
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO frog (gid, cid, interval, persist, fuzzy)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (gid, cid) DO UPDATE SET
                    interval = EXCLUDED.interval,
                    persist = EXCLUDED.persist
                """,
                *frog
            )


async def clear(pool: Pool, gid: int) -> None:
    """Remove all frog settings for this guild,."""
    if not await guild.get(pool, gid):  # guild not yet init, foreign key
        await guild.add(pool, gid)
        return  # impossible for there to be frogs

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                DELETE
                FROM frog
                WHERE gid = $1
                """,
                gid,
            )


async def get_all(pool: Pool) -> list[Record]:
    """Get all frog settings."""
    async with pool.acquire() as con:
        return await con.fetch(
            """
            SELECT gid, cid, interval, persist, fuzzy
            FROM frog
            """
        )
