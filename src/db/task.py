"""Defines SQL queries to make to the database for anything relate to a task."""
import logging

from asyncpg import Pool

from . import schema


_log = logging.getLogger(__name__)


async def add_task(pool: Pool, tsk: schema.TaskSchema):
    """Add task into database."""
    async with pool.acquire() as con:
        async with con.transaction():
            try:
                await con.execute(
                    """
                    INSERT INTO task (tag, run_at, payload)
                    VALUES ($1, $2, $3)
                    """,
                    *tsk,
                )
            except Exception as err:
                _log.error(err)
                return 1
            else:
                return 0


async def get_tasks(pool: Pool, module: str):
    """Fetch all tasks that match the module."""
    async with pool.acquire() as con:
        async with con.transaction():
            try:
                data = await con.fetch(
                    """
                    SELECT * FROM task
                    WHERE $1 = ANY(tag)
                    """,
                    module,
                )

            except Exception as err:
                _log.error(err)
                return None
            else:
                return data


async def drop_task(pool: Pool, id: int):
    """Drop a task from database, usually after handling it."""
    async with pool.acquire() as con:
        async with con.transaction():
            try:
                await con.execute(
                    """
                    DELETE FROM task
                    WHERE id = $1
                    """,
                    id,
                )
            except Exception as err:
                _log.error(err)
