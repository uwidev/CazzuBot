"""All direct database interactions related to modlogs."""
import logging

from asyncpg import Pool

from . import guild, schema, user


_log = logging.getLogger(__name__)


async def add_modlog(pool: Pool, log: schema.ModlogSchema):
    """Add modlog into database.

    cid is ignored when adding modlog, since cid is serialized per-guild.
    """
    # Foreign constraint dependencies
    if not await user.get_user(pool, log.uid):
        await user.add_user(pool, schema.UserSchema(log.uid))

    if not await guild.get_guild(pool, log.gid):
        await guild.add_guild(pool, schema.GuildSchema(log.gid))

    async with pool.acquire() as con:
        async with con.transaction():
            try:
                await con.execute(
                    """
                    INSERT INTO modlog
                        (gid, uid, log_type, given_on, status, expires_on, reason)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    """,
                    *log,
                )
            except Exception as err:
                _log.error(err)
                return 1
            else:
                return 0


async def get_modlogs(db: Pool, gid: int) -> dict:
    """Return modlogs for a specific guild."""
    # return await settings.search(db, Table.MODLOG, where("gid") == gid)
    async with db.acquire() as con:
        async with con.transaction():
            try:
                data = await con.fetch(
                    """
                    SELECT * FROM modlog
                    WHERE gid = $1
                    """,
                    gid,
                )
            except Exception as err:
                _log.error(err)
                return None
            else:
                return data
