"""Manages all queries about guilds."""
import logging

import pendulum
from asyncpg import Pool, Record, exceptions

from . import guild, table, user


_log = logging.getLogger(__name__)


async def add(pool: Pool, member: table.Member):
    async with pool.acquire() as con:
        # Foreign constraint dependencies
        if not await user.get(pool, member.uid):
            await user.add(pool, table.User(member.uid))

        if not await guild.get(pool, member.gid):
            await guild.add(pool, table.Guild(member.gid))

        # Create guild partition if not exists
        await create_partition_gid(pool, member.gid)

        async with con.transaction():
            try:
                await con.execute(
                    """
                    INSERT INTO member (gid, uid, exp_lifetime, exp_msg_cnt, exp_cdr)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    *member,
                )
            except Exception as err:
                _log.error(err)
            else:
                return 0


async def get(pool: Pool, gid: int, uid: int) -> Record:
    async with pool.acquire() as con:
        try:
            res = await con.fetchrow(
                """
                SELECT *
                FROM member
                WHERE uid = $1 AND gid = $2
                LIMIT 1
                """,
                uid,
                gid,
            )
        except Exception as err:
            _log.error(err)
        else:
            return res


async def update_exp(pool: Pool, member: table.Member):
    """Grant a user experience and update their experience cooldown.

    Cooldown should be the timestamp when cooldown expires, NOT DURATION.
    """
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE member
                SET exp_lifetime = $1,
                    exp_cdr = $2,
                    exp_msg_cnt = $3
                WHERE uid = $4 AND gid = $5
                """,
                member.exp_lifetime,
                member.exp_cdr,
                member.exp_msg_cnt,
                member.uid,
                member.gid,
            )


async def create_partition_gid(pool: Pool, gid: int):
    """Parition the experience database by gid.

    Only creates the table if it doesn't yet exist.
    """
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                f"""
                CREATE TABLE IF NOT EXISTS members_{gid}
                    PARTITION OF member
                FOR VALUES IN ({gid});
                """
            )


async def get_all_member_exp(pool: Pool, gid: int) -> list[Record]:
    """Get all experience from given gid."""
    async with pool.acquire() as con:
        return await con.fetch(
            """
            SELECT RANK() OVER (ORDER BY exp DESC) AS rank, uid, exp
            FROM member
            WHERE gid = $1
            ORDER BY exp DESC
            """,
            gid,
        )


async def get_rank_exp(pool: Pool, gid: int, uid: int) -> Record:
    """Get all experience from given gid."""
    async with pool.acquire() as con:
        return await con.fetchrow(
            """
            SELECT rank, exp
            FROM (
                SELECT RANK() OVER (ORDER BY exp DESC) AS rank, uid, exp
                FROM member
                WHERE gid = $1
                ORDER BY exp DESC
            ) AS members_ranked
            WHERE UID = $2
            LIMIT 1;
            """,
            gid,
            uid,
        )


async def reset_all_msg_cnt(pool: Pool):
    """Set all msg_cnt to 1 for daily reset."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                UPDATE member
                SET exp_msg_cnt = 1
                """
            )


async def reset_all_cdr(pool: Pool):
    """Set all cdr to now."""
    async with pool.acquire() as con:
        async with con.transaction():
            await con.execute(
                """
                    UPDATE member
                    SET exp_cdr = NOW()
                    """
            )
