"""Manages all queries about member's frogs."""

import logging

import pendulum
from asyncpg import Pool, Record, exceptions

from . import table


_log = logging.getLogger(__name__)


async def add(pool: Pool, gid: int, uid: int, *, frog: int = 0):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO member_frog
                SET frog = frog + $3
                WHERE gid = $1 AND uid = $2
                """,
                gid,
                uid,
                frog,
            )


async def modify_frog(pool: Pool, gid: int, uid: int, amount: int) -> None:
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE member_frog
                SET frog = frog + $3
                WHERE gid = $1 AND uid = $2
                """,
                gid,
                uid,
                amount,
            )
