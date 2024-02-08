"""Manages everything related to logging the raw events of experience gain.

Exp is stored per-message rather than added to a running value. They are also given a
timestamp. This allows for flexible queries and design of leaderboards, but requires
additional computation to calculate each member's cumulative experience per time-window.

There may potentially be a "lifetime" exp stored on the member, which can speed things.

If query performance is slow, consider building and keeping an internal cache of
pre-computed experiences.

Patitioning is done by timestamp, and then timestamp is partitioned by gid.
"""

import contextlib
import logging

import pendulum
from asyncpg import DuplicateTableError, InvalidObjectDefinitionError, Pool, Record

from . import guild, table, user, utility


_log = logging.getLogger(__name__)


async def add(pool: Pool, payload: table.MemberExpLog):
    """Log expereience gain entry."""
    await create_partition(pool, payload.gid)

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO member_exp_log (gid, uid, exp, at)
                VALUES ($1, $2, $3, $4)
                """,
                *payload,
            )


async def create_partition(pool: Pool, gid: int):
    """Partition member exp log as needed."""
    now = pendulum.now()
    start = pendulum.datetime(now.year, now.month, 1)
    end = start.add(months=1)

    await create_partition_monthly(pool, start, end)
    await create_index_on_date(pool, start)


async def create_partition_monthly(
    pool: Pool, start: pendulum.DateTime, end: pendulum.DateTime
):
    """Parition the experience log database by this month.

    Only creates the parition if it doesn't yet exist.
    """
    start_str = f"{start.year}_{start.month}"

    async with pool.acquire() as con:
        async with con.transaction():
            with contextlib.suppress(InvalidObjectDefinitionError):  # Already exists
                await con.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS exp_log_{start_str}
                        PARTITION OF member_exp_log
                        FOR VALUES FROM ('{start.to_date_string()}') TO ('{end.to_date_string()}')
                    ;
                    """
                )


async def create_partition_gid(pool: Pool, gid: int, date: pendulum.DateTime):
    """Parition the experience log database by gid.

    Only creates the parition if it doesn't yet exist.

    2023-11-2: Partitioning doesn't seem to increase performance, and perhaps seems to
        bloat design. Partitioning by month makes sense, but partitioning by month and
        gid? I think an index would be better suited for gid lookups...
    """
    start_str = f"{date.year}_{date.month}"

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS exp_log_{start_str}_{gid}
                    PARTITION OF exp_log_{start_str}
                    FOR VALUES IN ({gid});
                """
            )


async def create_index_on_date(pool: Pool, date: pendulum.DateTime):
    """Index the selected partition."""
    start_str = f"{date.year}_{date.month}"

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_exp_log_{start_str}
                ON exp_log_{start_str} (gid, uid)
                """
            )


async def get_monthly(pool: Pool, gid: int, uid: int, year: int, month: int) -> int:
    """Fetch a member's sum exp from the specified month."""
    date = pendulum.datetime(year, month, 1)
    date_str = f"{date.year}_{date.month}"

    async with pool.acquire() as con:
        return await con.fetchval(
            f"""
            SELECT sum(exp)
            FROM exp_log_{date_str}
            WHERE gid = $1 AND uid = $2
            """,
            gid,
            uid,
        )


async def get_seasonal_by_month(pool: Pool, gid: int, uid: int, year: int, month: int):
    """Call get_season() when season is as a month rather than season.

    Passed argument should still be natural counting, starting from 1.

    For the month to bucket into seasons, it must be zero indexed for floor division.
    0-2  -> 0
    3-5  -> 1
    6-8  -> 2
    9-11 -> 3
    """
    zero_indexed_month = month - 1
    return await get_seasonal(pool, gid, uid, year, zero_indexed_month // 3)


async def get_seasonal(pool: Pool, gid: int, uid: int, year: int, season: int) -> int:
    """Fetch a member's sum experience based on season.

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
        return await con.fetchval(
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


async def get_seasonal_bulk_ranked(pool: Pool, gid: int, year: int, season: int) -> int:
    """Fetch exp and ranks them of a guild's members.

    Seasons start from 0 and go to to 3.

    Return records are 'formatted' as records [[rank, uid, exp]]
    """
    if season < 0 or season > 3:  # noqa: PLR2004
        msg = "Seasons must be in the range of 0-3"
        _log.error(msg)
        raise ValueError(msg)

    start_month = 1 + 3 * season  # season months start 1 4 7 10
    interval = [pendulum.datetime(year, start_month, 1)]
    interval.append(interval[0] + pendulum.duration(months=3))  # [from, to]

    async with pool.acquire() as con:
        return await con.fetch(
            """
            SELECT RANK() OVER (ORDER BY exp DESC) AS rank, uid, exp
            FROM (SELECT uid, gid, sum(exp) as exp
                FROM member_exp_log
                WHERE gid = $1 AND at BETWEEN $2 AND $3
                GROUP BY uid, gid
                ) as source
            WHERE gid = $1
            ORDER BY exp DESC
            """,
            gid,
            interval[0],
            interval[1],
        )


async def get_seasonal_total_members(
    pool: Pool, gid: int, year: int, season: int
) -> int:
    """Return the count of all participants this season."""
    if season < 0 or season > 3:  # noqa: PLR2004
        msg = "Seasons must be in the range of 0-3"
        _log.error(msg)
        raise ValueError(msg)

    start_month = 1 + 3 * season  # season months start 1 4 7 10
    interval = [pendulum.datetime(year, start_month, 1)]
    interval.append(interval[0] + pendulum.duration(months=3))  # [from, to]

    async with pool.acquire() as con:
        return await con.fetchval(
            """
            SELECT COUNT(*)
            FROM (
                SELECT uid
                FROM member_exp_log
                WHERE gid = $1 AND at BETWEEN $2 AND $3
                GROUP BY uid
            ) as seasonal_uids
            """,
            gid,
            interval[0],
            interval[1],
        )


async def get_seasonal_total_members_by_month(
    pool: Pool, gid: int, year: int, month: int
) -> int:
    zero_indexed_month = month - 1
    return await get_seasonal_total_members(pool, gid, year, zero_indexed_month // 3)


async def get_total_members(
    pool: Pool,
    gid: int,
) -> int:
    async with pool.acquire() as con:
        return await con.fetchval(
            """
            SELECT COUNT(*)
            FROM (
                SELECT uid
                FROM member_exp_log
                WHERE gid = $1
                GROUP BY uid
            ) as seasonal_uids
            """,
            gid,
        )
