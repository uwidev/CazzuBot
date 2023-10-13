"""Defines SQL queries to make to the database for anything relate to a task."""
import logging

from asyncpg import Pool

from . import table


_log = logging.getLogger(__name__)


async def add(pool: Pool, tsk: table.Task):
    """Add task into database."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO task (tag, run_at, payload)
                VALUES ($1, $2, $3)
                """,
                *tsk,
            )


async def get(pool: Pool, module: str):
    """Fetch all tasks that match the module."""
    async with pool.acquire() as con:
        async with con.transaction():
            return await con.fetch(
                """
                SELECT * FROM task
                WHERE $1 = ANY(tag)
                """,
                module,
            )


async def drop(pool: Pool, id: int):
    """Drop a task from database, usually after handling it."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                DELETE FROM task
                WHERE id = $1
                """,
                id,
            )
