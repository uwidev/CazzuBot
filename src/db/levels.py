"""Levels abstraction queries.

Levels are derived from experience.
"""

import logging

import pendulum
from asyncpg import Pool, Record
from pendulum import DateTime

from src import levels_helper


_log = logging.getLogger(__name__)


async def get_lifetime_level(pool: Pool, gid: int, uid: int) -> int:
    """Fetch and calculate level from a member's lifetime experience."""
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

    return levels_helper.exp_to_level_cum(exp)


async def get_level_monthly(
    pool: Pool, gid: int, uid: int, year: int, month: int
) -> int:
    """Fetch and calculate level from a member's experience from the specified month."""
    date = pendulum.datetime(year, month, 1)
    date_str = f"{date.year}_{date.month}"

    async with pool.acquire() as con:
        exp = await con.fetchval(
            f"""
            SELECT sum(exp)
            FROM exp_log_{date_str}
            WHERE gid = $1 AND uid = $2
            """,
            gid,
            uid,
        )

    return levels_helper.level_from_exp(exp)


async def get_level_seasonal(
    pool: Pool, gid: int, uid: int, year: int, season: int
) -> int:
    """Fetch and calculate level from a member's experience based on season.

    Seasons start from 0 and go to to 3.
    """
    if season < 0 or season > 3:  # noqa: PLR2004
        msg = "Seasons must be in the range of 0-3"
        _log.error(msg)
        raise ValueError(msg)

    start_month = 1 + 3 * season  # season months start 1 4 7 10
    interval = [pendulum.datetime(year, start_month, 1)]
    interval.append(interval[0] + pendulum.duration(months=3))  # [from, to]

    async with pool.acquire() as con:
        exp = await con.fetchval(
            """
            SELECT sum(exp)
            FROM member_exp_log
            WHERE gid = $1 AND uid = $2 AND at BETWEEN $3 AND $4
            """,
            gid,
            uid,
            interval[0],
            interval[1],
        )

    return levels_helper.level_from_exp(exp)
