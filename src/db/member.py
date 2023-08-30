"""Manages all queries about guilds."""
import logging

from asyncpg import Pool, exceptions

from . import guild, schema, user


_log = logging.getLogger(__name__)


async def add_member(pool: Pool, member: schema.MemberSchema):
    async with pool.acquire() as con:
        # Foreign constraint dependencies
        if not await user.get_user(pool, member.uid):
            await user.add_user(pool, schema.UserSchema(member.uid))

        if not await guild.get_guild(pool, member.gid):
            await guild.add_guild(pool, schema.GuildSchema(member.gid))

        async with con.transaction():
            try:
                await con.execute(
                    """
                    INSERT INTO member (uid, gid)
                    VALUES ($1, $2)
                    """,
                    *member
                )
            except Exception as err:
                _log.error(err)
            else:
                return 0


async def get_member(pool: Pool, uid: int, gid: int):
    async with pool.acquire() as con:
        try:
            res = await con.fetchrow(
                """
                SELECT *
                FROM member
                WHERE uid = $1 AND gid = $2
                """,
                uid,
                gid,
            )
        except Exception as err:
            _log.error(err)
        else:
            return res
