"""Manages all queries for member experience functionality.

The member's lifetime experience is also precomputed in this table.

For more accurate experience, or for range-based queries, see member_exp_log.py
"""

import logging

from asyncpg import Pool, Record

from . import table, utility

_log = logging.getLogger(__name__)


@utility.fkey_member
async def add(pool: Pool, member_exp: table.MemberExp) -> None:
	# Foreign constraint dependencies
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO member_exp (gid, uid, lifetime, msg_cnt, cdr)
				VALUES ($1, $2, $3, $4, $5)
				""",
				*member_exp,
			)


async def get_one(pool: Pool, gid: int, uid: int) -> Record:
	async with pool.acquire() as con:
		return await con.fetchrow(
			"""
			SELECT *
			FROM member_exp
			WHERE uid = $1 AND gid = $2
			LIMIT 1
			""",
			uid,
			gid,
		)


async def update_exp(pool: Pool, member_exp: table.MemberExp) -> None:
	"""Grant a user experience and update their experience cooldown.

	Cooldown should be the timestamp when cooldown expires, NOT DURATION.
	"""
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE member_exp
				SET lifetime = $1,
					cdr = $2,
					msg_cnt = $3
				WHERE uid = $4 AND gid = $5
				""",
				member_exp.lifetime,
				member_exp.cdr,
				member_exp.msg_cnt,
				member_exp.uid,
				member_exp.gid,
			)


async def create_partition_gid(pool: Pool, gid: int) -> None:
	"""Parition the experience database by gid.

	Only creates the table if it doesn't yet exist.

	2023-02-11: Guild partitions are probably not that effective, using indexes instead.
	  Which is to say this is uselsss now, and probably to delete later.
	"""
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				f"""
				CREATE TABLE IF NOT EXISTS members_{gid}
					PARTITION OF member_exp
				FOR VALUES IN ({gid});
				"""
			)


async def get_exp_bulk_ranked(pool: Pool, gid: int) -> list[Record]:
	"""Get lifetime experience from given gid ordered descending."""
	async with pool.acquire() as con:
		return await con.fetch(
			"""
			SELECT RANK() OVER (ORDER BY lifetime DESC) AS rank, uid, lifetime
			FROM member_exp
			WHERE gid = $1
			ORDER BY lifetime DESC
			""",
			gid,
		)


async def reset_all_msg_cnt(pool: Pool):
	"""Set all msg_cnt to 1 for daily reset."""
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE member_exp
				SET msg_cnt = 1
				"""
			)


async def reset_all_cdr(pool: Pool) -> None:
	"""Set all cdr to now."""
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
					UPDATE member_exp
					SET cdr = NOW()
					"""
			)


async def sync_with_exp_logs(pool: Pool) -> None:
	"""Sum exp per member from message exp logs and set to lifetime."""
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE member_exp
				SET lifetime = source.exp
				FROM (
					SELECT uid, gid, sum(exp) as exp
					FROM member_exp_log
					GROUP BY uid, gid
					) as source
				WHERE member_exp.uid = source.uid and member_exp.gid = source.gid
				"""
			)
