"""Manages all queries about member's frogs."""

import logging

import pendulum
from asyncpg import Pool, Record, exceptions

from . import guild, member_frog_log, table, utility


_log = logging.getLogger(__name__)


@utility.fkey_member
async def add(pool: Pool, payload: table.MemberFrog):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO member_frog (gid, uid, normal, frozen)
                VALUES ($1, $2, $3, $4)
                """,
                *payload,
            )


@utility.fkey_member
async def upsert(pool: Pool, payload: table.MemberFrog):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO member_frog (gid, uid, frog)
                VALUES ($1, $2, $3)
                ON CONFLICT (gid, uid) DO UPDATE SET
                    frog = EXCLUDED.frog
                """,
                *payload,
            )


@utility.fkey_member
async def upsert_modify_frog(
    pool: Pool,
    payload: table.MemberFrog,
    modify: int,
    frog_type: table.FrogTypeEnum = table.FrogTypeEnum.NORMAL,
) -> None:
    gid = payload.gid
    uid = payload.uid
    frog_norm = payload.normal
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                f"""
                INSERT INTO member_frog (gid, uid, {frog_type.value})
                VALUES ($1, $2, $3)
                ON CONFLICT (gid, uid) DO UPDATE SET
                    {frog_type.value} = member_frog.{frog_type.value} + $4
                """,
                gid,
                uid,
                frog_norm,
                modify,
            )


async def get_frogs(
    pool: Pool,
    gid: int,
    uid: int,
    frog_type: table.FrogTypeEnum = table.FrogTypeEnum.NORMAL,
) -> int:
    """Return the total amount of normal frogs a user has."""
    async with pool.acquire() as con:
        return await con.fetchval(
            f"""
            SELECT {frog_type.value}
            FROM member_frog
            WHERE gid = $1 AND uid = $2
            """,
            gid,
            uid,
        )


async def get_members_frog_seasonal(
    pool: Pool, gid: int, year: int, season: int
) -> list[Record]:
    """Fetch frog captures and ranks them of all guild members.

    Acts more of an alias for more intuitive design.
    """
    return await member_frog_log.get_seasonal_bulk_ranked(pool, gid, year, season)


async def get_members_frog_seasonal_by_month(
    pool: Pool, gid: int, year: int, month: int
) -> list[Record]:
    """Fetch frog captures and ranks them of all guild members.

    Acts more of an alias for more intuitive design.
    """
    zero_indexed_month = month - 1
    return await get_members_frog_seasonal(pool, gid, year, zero_indexed_month // 3)
