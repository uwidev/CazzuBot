"""Levels abstraction queries and guild settings related to levels.

Levels are derived from experience.
"""

import logging

from asyncpg import Pool, Record

from src import levels_helper

from . import guild, member_exp_log, table

_log = logging.getLogger(__name__)


async def add(pool: Pool, level: table.RankThreshold):
	if not await guild.get(pool, level.gid):  # guild not yet init
		await guild.add(pool, level.gid)

	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO level (gid)
				VALUES ($1)
				""",
				*level,
			)


async def get(pool: Pool, gid: int) -> list[Record]:
	async with pool.acquire() as con:
		return await con.fetch(
			"""
			SELECT *
			FROM level
			WHERE gid = $1
			""",
			gid,
		)


async def set_message(pool: Pool, gid: int, encoded_json: str):
	if not await get(pool, gid):  # this not yet init
		payload = table.Level(gid, None)
		await add(pool, payload)

	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE level
				SET message = $2
				WHERE gid = $1
				""",
				gid,
				encoded_json,
			)


async def get_message(pool: Pool, gid: int) -> list[Record]:
	if not await get(pool, gid):  # this not yet init
		payload = table.Level(gid, None)
		await add(pool, payload)

	async with pool.acquire() as con:
		return await con.fetchval(
			"""
			SELECT message
			FROM level
			WHERE gid = $1
			""",
			gid,
		)


async def get_lifetime_level(pool: Pool, gid: int, uid: int) -> int:
	"""Fetch and calculate level from a member's lifetime experience."""
	async with pool.acquire() as con:
		exp = await con.fetchval(
			"""
			SELECT lifetime
			FROM member_exp
			WHERE gid = $1 AND uid = $2
			""",
			gid,
			uid,
		)

	return levels_helper.level_from_exp(exp)


async def get_monthly(
	pool: Pool, gid: int, uid: int, year: int, month: int
) -> int:
	"""Fetch and calculate level from a member's experience from the specified month."""
	exp = await member_exp_log.get_monthly(pool, gid, uid, year, month)
	return levels_helper.level_from_exp(exp)


async def get_seasonal(
	pool: Pool, gid: int, uid: int, year: int, season: int
) -> int:
	"""Fetch and calculate level from a member's experience based on season.

	Seasons start from 0 and go to to 3.
	"""
	exp = await member_exp_log.get_seasonal(pool, gid, uid, year, season)
	return levels_helper.level_from_exp(exp)


async def get_seasonal_by_month(
	pool: Pool, gid: int, uid: int, year: int, month: int
) -> int:
	"""Fetch and calculate level from a member's experience based on season.

	Connverts natural counting month to zero indexed, then bins it.
	"""
	exp = await member_exp_log.get_seasonal_by_month(
		pool, gid, uid, year, month
	)
	return levels_helper.level_from_exp(exp)
