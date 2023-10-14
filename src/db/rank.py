"""For setting ranked roles per-guild in database."""
import logging

import pendulum
from asyncpg import Pool, Record, exceptions

from . import table


_log = logging.getLogger(__name__)


async def add(pool: Pool, rank: table.Rank):
    async with pool.acquire() as con:
        async with con.transaction():
            await pool.execute(
                """
                INSERT INTO rank (gid, rid, threshold)
                VALUES ($1, $2, $3)
                """,
                *rank
            )


async def get(pool: Pool, gid: int) -> list[Record]:
    async with pool.acquire() as con:
        return await con.fetch(
            """
            SELECT rid, threshold
            FROM rank
            WHERE gid = $1
            ORDER BY threshold
            """,
            gid,
        )


async def delete(pool: Pool, gid: int, arg: int):
    """Delete rank in db, first looking for rid then by threshold."""
    async with pool.acquire() as con:
        async with con.transaction():
            await pool.execute(
                """
                DELETE FROM rank
                WHERE rid = $1 OR threshold = $1
                """,
                arg,
            )


async def drop(pool: Pool, gid: int):
    """Delete all ranks associated with gid."""
    async with pool.acquire() as con:
        async with con.transaction():
            await pool.execute(
                """
                DELETE FROM rank
                WHERE gid = $1
                """,
                gid,
            )
