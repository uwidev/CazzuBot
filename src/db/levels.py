"""Levels abstraction queries.

Levels are derived from experience.
"""

import logging

from asyncpg import Pool, Record

from src.levels_helper import cum_exp_to


_log = logging.getLogger(__name__)


async def get_lifetime_level(pool: Pool, gid: int, uid: int) -> Record:
    async with pool.acquire() as con:
        exp = await con.fetchval(
            """
            SELECT exp_lifetime
            FROM member
            WHERE gid = $1 AND uid = $2
            """,
            gid,
            uid,
        )

    return cum_exp_to(exp)
