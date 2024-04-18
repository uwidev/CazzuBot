"""Manages all queries for a guild's welcome settings."""

import logging

from asyncpg import Pool, Record

from . import table


_log = logging.getLogger(__name__)


async def add(pool: Pool, gid: int):
    """Add guild to database welcome.

    Should consider taking a table.Welcome object instead for standardization.
    """
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO welcome (gid)
                VALUES ($1)
                """,
                gid,
            )


async def get(pool: Pool, gid: int) -> Record:
    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            SELECT *
            FROM welcome
            WHERE gid = $1
            """,
            gid,
        )


async def set_enabled(pool: Pool, gid: int, val: bool):  # noqa: FBT001
    if not await get(pool, gid):  # if welcome entry for this guild not exists, make it
        await add(pool, gid)

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE welcome
                SET enabled = $1
                """,
                val,
            )


async def set_verify_first(pool: Pool, gid: int, val: bool):  # noqa: FBT001
    if not await get(pool, gid):  # if welcome entry for this guild not exists, make it
        await add(pool, gid)

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE welcome
                SET verify_first = $1
                """,
                val,
            )


async def set_default_rid(pool: Pool, gid: int, rid: int):
    if not await get(pool, gid):  # if welcome entry for this guild not exists, make it
        await add(pool, gid)

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE welcome
                SET default_rid = $1
                """,
                rid,
            )


async def set_cid(pool: Pool, gid: int, cid: int):
    if not await get(pool, gid):  # if welcome entry for this guild not exists, make it
        await add(pool, gid)

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE welcome
                SET cid = $1
                """,
                cid,
            )


async def set_message(pool: Pool, gid: int, message: str):
    if not await get(pool, gid):  # if welcome entry for this guild not exists, make it
        await add(pool, gid)

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE welcome
                SET message = $1
                """,
                message,
            )


async def get_enabled(pool: Pool, gid: int) -> bool:
    if not await get(pool, gid):  # return false, no need to create
        return False

    async with pool.acquire() as con:
        return await con.fetchval(
            """
            SELECT enabled
            FROM welcome
            WHERE gid = $1
            """,
            gid,
        )


async def get_message(pool: Pool, gid: int) -> str:
    if not await get(pool, gid):  # return false, no need to create
        await add(pool, gid)

    async with pool.acquire() as con:
        return await con.fetchval(
            """
            SELECT message
            FROM welcome
            WHERE gid = $1
            """,
            gid,
        )


async def get_cid(pool: Pool, gid: int) -> int:
    if not await get(pool, gid):  # return false, no need to create
        return False

    async with pool.acquire() as con:
        return await con.fetchval(
            """
            SELECT cid
            FROM welcome
            WHERE gid = $1
            """,
            gid,
        )


async def get_payload(pool: Pool, gid: int) -> Record:
    """Get all neccessary information to handle welcoming users."""
    if not await get(pool, gid):  # return false, no need to create
        return False

    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            SELECT enabled, cid, message, default_rid, mode, monitor_rid
            FROM welcome
            WHERE gid = $1
            """,
            gid,
        )


async def set_mode(pool: Pool, gid: int, mode: table.WelcomeModeEnum):
    """Get all neccessary information to handle welcoming users."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE welcome
                SET mode = $2
                WHERE gid = $1
                """,
                gid,
                mode,
            )


async def set_monitor_rid(pool: Pool, gid: int, rid: int):
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE welcome
                SET monitor_rid = $2
                WHERE gid = $1
                """,
                gid,
                rid,
            )
