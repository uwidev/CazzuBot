"""For managing ranked roles per-guild in database.

This is not the settings, for that, see db.rank.
"""
import logging

import pendulum
from asyncpg import Pool, Record, exceptions

from . import level, table


_log = logging.getLogger(__name__)


async def add(pool: Pool, rank: table.RankThreshold):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO rank_threshold (gid, rid, threshold)
                VALUES ($1, $2, $3)
                """,
                *rank
            )


async def get(pool: Pool, gid: int) -> list[Record]:
    async with pool.acquire() as con:
        return await con.fetch(
            """
            SELECT rid, threshold
            FROM rank_threshold
            WHERE gid = $1
            ORDER BY threshold
            """,
            gid,
        )


async def delete(pool: Pool, gid: int, arg: int):
    """Delete rank in db, first looking for rid then by threshold."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                DELETE FROM rank_threshold
                WHERE rid = $1 OR threshold = $1
                """,
                arg,
            )


async def batch_delete(pool: Pool, gid: int, rids: list):
    """Delete a batch of rids from database."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                DELETE FROM rank_threshold
                WHERE rid = ANY($1)
                """,
                rids,
            )


async def drop(pool: Pool, gid: int):
    """Delete all ranks associated with gid."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                DELETE FROM rank_threshold
                WHERE gid = $1
                """,
                gid,
            )


def _calc_min_rank(rank_threshold: list[Record], level) -> tuple[int, int]:
    """Naively determine rank based on level from list of records.

    This is the same function as rank.calc_min_rank (or at least should be).
    The only difference is that it doesn't return the index.
    """
    if not rank_threshold:
        return 0

    if level < rank_threshold[0]["threshold"]:
        return None, None

    for i in range(1, len(rank_threshold)):
        if level < rank_threshold[i]["threshold"]:
            return rank_threshold[i - 1]["rid"]

    return rank_threshold[-1]["rid"]


async def of_member(pool: Pool, gid: int, uid: int) -> int:
    """Return the rank of a member, None if no role rank.

    Is based on seasonal experience.
    """
    ranks_raw = await get(pool, gid)

    now = pendulum.now()
    lvl = await level.get_seasonal(pool, gid, uid, now.year, now.month // 3)

    return _calc_min_rank(ranks_raw, lvl)
