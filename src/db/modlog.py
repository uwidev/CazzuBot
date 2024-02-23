"""All direct database interactions related to modlogs."""

import logging

from asyncpg import Pool

from . import guild, table, user


_log = logging.getLogger(__name__)


async def add(pool: Pool, log: table.Modlog):
    """Add modlog into database.

    cid is ignored when adding modlog, since cid is serialized per-guild.
    """
    # Foreign constraint dependencies
    if not await user.get(pool, log.uid):
        await user.add(pool, table.User(log.uid))

    if not await guild.get(pool, log.gid):
        await guild.add(pool, table.Guild(log.gid))

    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                INSERT INTO modlog
                    (gid, uid, log_type, given_on, status, expires_on, reason)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                *log,
            )


async def get(db: Pool, gid: int) -> dict:
    """Return modlogs for a specific guild."""
    # return await settings.search(db, Table.MODLOG, where("gid") == gid)
    async with db.acquire() as con:
        async with con.transaction():
            data = await con.fetch(
                """
                SELECT * FROM modlog
                WHERE gid = $1
                """,
                gid,
            )


# async def create_partition_gid(pool: Pool, gid: int):
#     """Parition the experience database by gid.

#     Only creates the table if it doesn't yet exist.
#     """
#     async with pool.acquire() as con:
#         async with con.transaction():
#             await con.execute(
#                 f"""
#                 CREATE TABLE IF NOT EXISTS modlog_{gid}
#                     PARTITION OF modlog
#                 FOR VALUES IN ({gid});
#                 """
#             )
