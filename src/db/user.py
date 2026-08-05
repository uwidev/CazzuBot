"""Manages all queries about users."""

import logging

from asyncpg import Pool

from . import table, utility

_log = logging.getLogger(__name__)


async def add(pool: Pool, user: table.User):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO "user" (uid)
				VALUES ($1)
				""",
				user.uid,
			)


async def get(pool: Pool, uid: int) -> table.User | None:
	async with pool.acquire() as con:
		record =  await con.fetchrow(
			"""
			SELECT *
			FROM "user"
			WHERE uid = $1
			""",
			uid,
		)

		return table.User.from_record(record) if record else None


def init():
	utility.insert_uid = add
