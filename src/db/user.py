"""Manages all queries about users."""

import logging

from asyncpg import Pool, exceptions

from . import table, utility


_log = logging.getLogger(__name__)


async def add(pool: Pool, user: table.User):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO "user" (uid)
                VALUES ($1)
                """,
                user.uid,
            )


async def get(pool: Pool, uid: int):
    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            SELECT *
            FROM "user"
            WHERE uid = $1
            """,
            uid,
        )


def init():
    utility.insert_uid = add
