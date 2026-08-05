"""Handle frog spawn database interactions."""

import logging

from asyncpg import Pool, Record

from . import guild, table, utility

_log = logging.getLogger(__name__)


@utility.fkey_channel
async def add(pool: Pool, frog: table.FrogSpawn) -> None:
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO frog_spawn (gid, cid, interval, persist)
				VALUES ($1, $2, $3, $4, $5)
				""",
				*frog,
			)


@utility.fkey_channel
async def upsert(pool: Pool, spawn: table.FrogSpawn) -> None:
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO frog_spawn (gid, cid, interval, persist, fuzzy)
				VALUES ($1, $2, $3, $4, $5)
				ON CONFLICT (gid, cid) DO UPDATE SET
					interval = EXCLUDED.interval,
					persist = EXCLUDED.persist
				""",
				*spawn,
			)


async def clear(pool: Pool, gid: int) -> None:
	"""Remove all frog settings for this guild,."""
	if not await guild.get(pool, gid):	# guild not yet init, foreign key
		await guild.add(pool, gid)
		return	# impossible for there to be frogs

	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				DELETE
				FROM frog_spawn
				WHERE gid = $1
				""",
				gid,
			)


async def get_all(pool: Pool) -> list[table.FrogSpawn]:
	"""Get all frog settings."""
	async with pool.acquire() as con:
		records = await con.fetch(
			"""
			SELECT *
			FROM frog_spawn
			"""
		)

		return [table.FrogSpawn.from_record(r) for r in records if r]


async def get(pool: Pool, gid: int) -> table.FrogSpawn | None:
	"""Get a guild's frog settings."""
	async with pool.acquire() as con:
		record = await con.fetchrow(
			"""
			SELECT *
			FROM frog_spawn
			WHERE gid = $1
			""",
			gid,
		)

		return table.FrogSpawn.from_record(record) if record else None


@utility.fkey_gid
async def set_message(pool: Pool, gid: int, json_d: dict):
	"""Set json message for on frog capture."""
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE frog_spawn
				SET message = $2
				WHERE gid = $1
				""",
				gid,
				json_d,
			)
