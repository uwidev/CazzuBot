"""Manages persistent data for bot operations, such as settings and flags."""

import datetime
import logging

from asyncpg import Pool

_log = logging.getLogger(__name__)


async def get_last_daily(pool: Pool) -> datetime.datetime:
	async with pool.acquire() as con:
		return await con.fetchval(
			"""
				SELECT value
				FROM internal
				WHERE field = 'last_daily'
				"""
		)


async def set_last_daily(pool: Pool, timestamp: datetime.datetime):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(	# does upsert
				"""
				INSERT INTO internal (field, value)
				VALUES ('last_daily', $1)
				ON CONFLICT (field) DO UPDATE SET
					value = EXCLUDED.value
				""",
				timestamp.isoformat(),
			)


async def get_last_quarterly(pool: Pool) -> datetime.datetime:
	async with pool.acquire() as con:
		return await con.fetchval(
			"""
				SELECT value
				FROM internal
				WHERE field = 'last_quarterly'
				"""
		)


async def set_last_quarterly(pool: Pool, timestamp: datetime.datetime):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(	# does upsert
				"""
				INSERT INTO internal (field, value)
				VALUES ('last_quarterly', $1)
				ON CONFLICT (field) DO UPDATE SET
					value = EXCLUDED.value
				""",
				timestamp.isoformat(),
			)
