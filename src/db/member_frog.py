"""Manages all queries about member's frogs."""

import logging

import pendulum
from asyncpg import Pool, Record, exceptions

from . import guild, table, user, utility


_log = logging.getLogger(__name__)


@utility.fkey_member
async def add(pool: Pool, payload: table.MemberFrog):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO member_frog (gid, uid, frog)
                VALUES ($1, $2, $3)
                """,
                *payload
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
                *payload
            )


@utility.fkey_member
async def upsert_modify_frog(
    pool: Pool, payload: table.MemberFrog, modify: int
) -> None:
    gid = payload.gid
    uid = payload.uid
    frog = payload.frog
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO member_frog (gid, uid, frog)
                VALUES ($1, $2, $3)
                ON CONFLICT (gid, uid) DO UPDATE SET
                    frog = member_frog.frog + $4
                """,
                gid,
                uid,
                frog,
                modify,
            )


async def get_amount(pool: Pool, gid: int, uid: int) -> int:
    async with pool.acquire() as con:
        return await con.fetchval(
            """
            SELECT frog
            FROM member_frog
            WHERE gid = $1 AND uid = $2
            """,
            gid,
            uid,
        )
