"""Manages association junction table for member-rank."""
import logging

import pendulum
from asyncpg import Pool, exceptions

from . import table


_log = logging.getLogger(__name__)


async def add(pool: Pool, mrank: table.MemberRank):
    """Add rank onto member in database."""
    async with pool.acquire() as con:
        async with con.transaction():
            await pool.execute(
                """
                INSERT INTO member_rank (gid, uid, rid)
                VALUES ($1, $2, $3)
                """,
                *mrank
            )


async def get(pool: Pool, gid: int, uid: int):
    """Get all ranks associated with this member."""
    async with pool.acquire() as con:
        async with con.transaction():
            return await pool.fetch(
                """
                SELECT rid
                FROM member_rank
                WHERE gid = $1 AND uid = $2
                """,
                gid,
                uid,
            )
