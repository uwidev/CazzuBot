"""Manages all queries about users."""
import logging

from asyncpg import Pool, exceptions

from . import schema


_log = logging.getLogger(__name__)


async def get_user(pool: Pool, uid: int):
    async with pool.acquire() as con:
        try:
            res = await con.fetchrow(
                """
                SELECT *
                FROM "user"
                WHERE uid = $1
                """,
                uid,
            )
        except Exception as err:
            _log.error(err)
        else:
            return res


async def add_user(pool: Pool, user: schema.UserSchema):
    async with pool.acquire() as con:
        async with con.transaction():
            try:
                await con.execute(
                    """
                    INSERT INTO "user" (uid)
                    VALUES ($1)
                    """,
                    user.uid,
                )
            except Exception as err:
                _log.error(err)
                return 1
            else:
                return 0
