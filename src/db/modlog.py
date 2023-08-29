"""All direct database interactions related to modlogs."""
import logging

from asyncpg import Pool

from src.db.schema import ModlogSchema


_log = logging.getLogger(__name__)


async def add_modlog(db: Pool, log: ModlogSchema):
    """Add modlog into database.

    cid is ignored when adding modlog, since cid is serialized per-guild.
    """
    # return await _insert(db, Table.MODLOG, log)
    async with db.acquire() as con:
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
