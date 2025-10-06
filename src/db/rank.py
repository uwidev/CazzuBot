"""For managing ranked role operations.

For specific operations on the rannked role list themselves, see db.ranked_thresholds.
"""

import logging

from asyncpg import Pool, Record

from . import guild, table, utility

_log = logging.getLogger(__name__)


async def add(
	pool: Pool,
	rank: table.Rank,
	*,
	mode: table.WindowEnum = table.WindowEnum.SEASONAL,
):
	"""Add a Rank object into the database."""
	if not await guild.get(
		pool, rank.gid
	):	# guild not yet init, foreign key
		await guild.add(pool, rank.gid)

	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO rank (gid, message, mode)
				VALUES ($1, $2, $3)
				""",
				*rank,
			)


async def init(
	pool: Pool,
	gid: int,
	*,
	mode: table.WindowEnum = table.WindowEnum.SEASONAL,
):
	"""Initialize the minimal for operational database queries."""
	if not await guild.get(pool, gid):	# guild not yet init, foreign key
		await guild.add(pool, gid)

	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO rank (gid, mode)
				VALUES ($1, $2)
				""",
				gid,
				mode,
			)


@utility.retry(on_none=init)
async def get(
	pool: Pool,
	gid: int,
	*,
	mode: table.WindowEnum = table.WindowEnum.SEASONAL,
) -> Record:
	"""Return rank row in a specific order for unpacking and else.

	Less overhead than individually calling for each column.
	"""
	async with pool.acquire() as con:
		return await con.fetchrow(
			"""
			SELECT gid, enabled, keep_old, message
			FROM rank
			WHERE gid = $1 and mode = $2
			""",
			gid,
			mode,
		)


@utility.retry(on_none=init)
async def set_message(
	pool: Pool,
	gid: int,
	encoded_json: str,
	*,
	mode: table.WindowEnum = table.WindowEnum.SEASONAL,
):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE rank
				SET message = $2
				WHERE gid = $1 and mode = $3
				""",
				gid,
				encoded_json,
				mode,
			)
			return 0


@utility.retry(on_none=init)
async def set_enabled(
	pool: Pool,
	gid: int,
	val: bool,
	*,
	mode: table.WindowEnum = table.WindowEnum.SEASONAL,
):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE rank
				SET enabled = $2
				WHERE gid = $1 and mode = $3
				""",
				gid,
				val,
				mode,
			)
			return 0


@utility.retry(on_none=init)
async def set_keep_old(
	pool: Pool,
	gid: int,
	val: bool,
	*,
	mode: table.WindowEnum = table.WindowEnum.SEASONAL,
):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE rank
				SET keep_old = $2
				WHERE gid = $1 and mode = $3
				""",
				gid,
				val,
				mode,
			)
			return 0


@utility.retry(on_none=init)
async def get_message(
	pool: Pool,
	gid: int,
	*,
	mode: table.WindowEnum = table.WindowEnum.SEASONAL,
) -> list[Record]:
	async with pool.acquire() as con:
		return await con.fetchval(
			"""
			SELECT message
			FROM rank
			WHERE gid = $1 and mode = $2
			""",
			gid,
			mode,
		)


@utility.retry(on_none=init)
async def get_enabled(
	pool: Pool,
	gid: int,
	*,
	mode: table.WindowEnum = table.WindowEnum.SEASONAL,
) -> list[Record]:
	"""Return if ranks are enabled."""
	async with pool.acquire() as con:
		return await con.fetchval(
			"""
			SELECT enabled
			FROM rank
			WHERE gid = $1 and mode = $2
			""",
			gid,
			mode,
		)


@utility.retry(on_none=init)
async def get_keep_old(
	pool: Pool,
	gid: int,
	*,
	mode: table.WindowEnum = table.WindowEnum.SEASONAL,
) -> list[Record]:
	"""Return if older ranks should be retained."""
	async with pool.acquire() as con:
		return await con.fetchval(
			"""
			SELECT keep_old
			FROM rank
			WHERE gid = $1 and mode = $2
			""",
			gid,
			mode,
		)
