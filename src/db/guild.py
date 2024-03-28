"""Handles general direct interactions with the database.

For module-specific queries, see other files in src.db

Asyncpg follows native PostgreSQL for query arguments $n. In other words, when writing a
query, you should NOT do a string format on the query. Rather, additional arguments are
given which will be substituted into the string after internal sanitation.
"""

import logging
from enum import Enum

from asyncpg import Pool, Record
from discord.ext import commands

from . import member_exp, member_exp_log, table, utility


_log = logging.getLogger(__name__)


async def add(pool: Pool, guild: table.Guild):
    """Insert a new entry into guild settings with default values."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO guild (gid)
                VALUES ($1)
                """,
                guild.gid,
            )


def req_mute_id():
    """Decorate to ensure mute role id is set."""

    async def predicate(ctx):
        if not await get_mute_id(ctx.bot.pool, ctx.guild.id):
            return False

        return True

    return commands.check(predicate)


async def set_mute_id(pool: Pool, gid: int, role: int):
    """Set the mute role on guild settings."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE guild
                SET mute_role = ($1)
                WHERE gid = $2
                """,
                role,
                gid,
            )


async def get_mute_id(pool: Pool, gid: int) -> int:
    """Get a guild's mute role."""
    async with pool.acquire() as con:
        return await con.fetchval(
            """
            SELECT mute_role
            FROM guild
            WHERE gid = $1
            """,
            gid,
        )


async def get(pool: Pool, gid: int):
    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            SELECT *
            FROM guild
            WHERE gid = $1
            """,
            gid,
        )


async def get_members_exp_seasonal(
    pool: Pool, gid: int, year: int, season: int
) -> list[Record]:
    """Fetch exp and ranks them of all guild members.

    Acts more of an alias for more intuitive design.
    """
    return await member_exp_log.get_seasonal_bulk_ranked(pool, gid, year, season)


async def get_members_exp_seasonal_by_month(
    pool: Pool, gid: int, year: int, month: int
) -> list[Record]:
    """Fetch exp and ranks them of all guild members.

    Acts more of an alias for more intuitive design.
    """
    zero_indexed_month = month - 1
    return await get_members_exp_seasonal(pool, gid, year, zero_indexed_month // 3)


async def get_members_exp_ranked(pool: Pool, gid: int) -> list[Record]:
    """Fetch lifetime exp and ranks them of all guild members.

    Acts more of an alias for more intuitive design.
    """
    return await member_exp.get_exp_bulk_ranked(pool, gid)


def init():
    utility.insert_gid = add
