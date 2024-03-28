"""Manages all queries about member."""

import logging

import pendulum
from asyncpg import Pool, Record, exceptions

from . import guild, table, user, utility


_log = logging.getLogger(__name__)


@utility.fkey_uid
@utility.fkey_gid
async def add(pool: Pool, payload: table.Member):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO member (gid, uid)
                VALUES ($1, $2)
                """,
                *payload
            )


def init():
    utility.insert_member = add
