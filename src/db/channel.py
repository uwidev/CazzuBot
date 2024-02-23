"""Manages all queries about channel."""

import logging

import pendulum
from asyncpg import Pool, Record, exceptions

from . import guild, table, user, utility


_log = logging.getLogger(__name__)


@utility.fkey_gid
async def add(pool: Pool, payload: table.Channel):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO channel (gid, cid)
                VALUES ($1, $2)
                """,
                *payload
            )


def init():
    utility.insert_cid = add


init()
