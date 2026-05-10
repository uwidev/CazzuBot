"""Manages counter-related configs."""

import logging

from asyncpg import Pool, Record

from . import table, utility

_log = logging.getLogger(__name__)

async def add(pool: Pool, payload: table.Counter):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO counter (gid, mid, count)
				VALUES ($1, $2, $3)
				""",
				*payload
			)

async def get_counters(pool: Pool, gid: int) -> [int]:
	async with pool.acquire() as con:
		return await con.fetch(
			"""
			SELECT mid, count
			FROM counter
			WHERE gid = $1
			""",
			gid
		)

async def update_count(pool:Pool, mid: int, count: int):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE counter
				SET count = $2
				WHERE mid = $1
				""",
				mid, count
			)
