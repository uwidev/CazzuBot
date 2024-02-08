"""Defines SQL queries to make to the database for anything relate to a task."""

import logging

from asyncpg import Pool
from pendulum import DateTime

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


# async def get_by_tag(pool: Pool, *, tag: str = None, tags: list = None):
#     """Fetch all tasks that match the tag(s)."""
#     if not ((tag and not tags) or (not tag and tags)):
#         msg = "Must have tag or tags, not both."
#         raise XORError(msg)

#     if tag:
#         tags = [tag]

#     async with pool.acquire() as con:
#         async with con.transaction():
#             return await con.fetch(
#                 """
#                 SELECT * FROM task
#                 WHERE $1::character varying[] <@ tag  -- subset operator
#                 """,
#                 tags,
#             )


async def get(pool: Pool, *, payload: dict = {}, tag: list[str] = []):
    """Find matching rows whose tags and payload are a superset of provided.

    No payload or tag returns all tasks.
    """
    async with pool.acquire() as con:
        return await con.fetch(
            """
            SELECT * FROM task
            WHERE $1::character varying[] <@ tag AND $2::jsonb <@ payload::jsonb
            """,
            tag,
            payload,
        )


async def get_one(pool: Pool, *, payload: dict = {}, tag: list[str] = []):
    """Find one matching rows whose tags and payload are a superset of provided.

    No payload or tag returns all tasks.
    """
    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            SELECT * FROM task
            WHERE $1::character varying[] <@ tag AND $2::jsonb <@ payload::jsonb
            """,
            tag,
            payload,
        )


async def drop_one(pool: Pool, id: int):
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


async def drop(pool: Pool, *, payload: dict = {}, tag: list[str] = []):
    """Delete all tasks whoses tags and payload is a superset of provided.

    Dangerous, make sure you know what you're doing.
    """
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                DELETE FROM task
                WHERE $1::character varying[] <@ tag AND $2::jsonb <@ payload::jsonb
                """,
                tag,
                payload,
            )


# async def drop_frog(pool: Pool, gid: int, cid: int):
#     """Drop frog tasks given a gid and cid."""
#     async with pool.acquire() as con:
#         async with con.transaction():
#             await con.execute(
#                 """
#                 DELETE FROM task
#                 WHERE ('{"gid": ' || $1 || '}')::jsonb <@ payload::jsonb AND ('{"cid": ' || $2 || '}')::jsonb <@ payload::jsonb
#                 """,
#                 str(gid),
#                 str(cid),
#             )


async def frog_update_run(pool: Pool, id: int, run_at: DateTime):
    """Update run_at interval on a frog task,."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE task
                SET run_at = $2
                WHERE id = $1
                """,
                id,
                run_at,
            )


async def frog_update(pool: Pool, id: int, run_at: DateTime, payload: dict):
    """Update all run_at and payload.

    Does not update tag, so might be slightly misleading.
    """
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE task
                SET run_at = $2, payload = $3
                WHERE id = $1
                """,
                id,
                run_at,
                payload,
            )


class XORError(Exception):
    pass
