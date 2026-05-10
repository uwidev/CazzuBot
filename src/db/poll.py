"""Manages poll-related operations."""

import logging

from asyncpg import Pool, Record

from . import table, user

_log = logging.getLogger(__name__)


async def add_poll(pool: Pool, payload: table.Poll) -> int:
	"""Register the poll into the database.

	Returns the ID of this poll.
	"""
	async with pool.acquire() as con:
		async with con.transaction():
			return await con.fetchval(
				"""
				INSERT INTO poll (gid, title, description, max_vote)
				VALUES ($1, $2, $3, $4)
				RETURNING id
				""",
				*payload,
			)


async def get_poll(pool: Pool, gid: int, pid: int) -> Record | None:
	async with pool.acquire() as con:
		return await con.fetchrow(
			"""
			SELECT *
			FROM poll
			WHERE gid = $1 and id = $2
			""",
			gid,
			pid,
		)


async def set_mid(pool: Pool, gid: int, pid: int, mid: int):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE poll
				SET mid = $3
				WHERE gid = $1 and id = $2
				""",
				gid,
				pid,
				mid,
			)


async def get_mid(pool: Pool, gid: int, pid: int) -> int:
	async with pool.acquire() as con:
		async with con.transaction():
			return await con.fetchval(
				"""
				SELECT mid
				FROM poll
				WHERE gid = $1 AND id = $2
				""",
				gid,
				pid,
			)

async def open(pool: Pool, gid: int, pid: int):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				UPDATE poll
				SET open = true
				WHERE gid = $1 and id = $2
				""",
				gid,
				pid,
			)



async def add_item(pool: Pool, payload: table.PollItem):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO poll_item (gid, pid)
				VALUES ($1, $2)
				""",
				*payload,
			)


async def add_items_dummy(pool: Pool, gid: int, pid: int, n: int):
	"""Insert N rows of (gid, int) into poll_item."""
	values = [(gid, pid) for _ in range(n)]

	async with pool.acquire() as con:
		async with con.transaction():
			await con.executemany(
				"""
				INSERT INTO poll_item (gid, pid)
				VALUES ($1, $2)
				RETURNING id
				""",
				values,
			)


async def get_items(pool: Pool, gid: int, pid: int):
	async with pool.acquire() as con:
		return await con.fetch(
			"""
			SELECT *
			FROM poll_item
			WHERE gid = $1 AND pid = $2
			""",
			gid,
			pid,
		)


async def add_vote(pool: Pool, payload: table.PollVote):
	uid = payload.uid
	if not await user.get(pool, uid):
		await user.add(pool, table.User(uid))
	

	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO poll_vote (gid, pid, iid, uid)
				VALUES ($1, $2, $3, $4)
				ON CONFLICT (unique column)
				DO UPDATE SET count = poll_vote.count + 1
				""",
				*payload,
			)


async def add_votes(pool: Pool, votes: [table.PollVote]):
	uid = votes[0].uid
	if not await user.get(pool, uid):
		await user.add(pool, table.User(uid))

	payloads = [tuple(payload) for payload in votes]

	async with pool.acquire() as con:
		async with con.transaction():
			await con.executemany(
				"""
				INSERT INTO poll_vote (gid, pid, iid, uid)
				VALUES ($1, $2, $3, $4)
				ON CONFLICT (gid, pid, iid, uid)
				DO UPDATE SET count = poll_vote.count + 1
				""",
				payloads,
			)


async def drop_user_on_poll(pool: Pool, gid: int, pid: int, uid: int):
	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				DELETE FROM poll_vote
				WHERE gid = $1 and pid = $2 and uid = $3
				""",
				gid,
				pid,
				uid,
			)

async def get_votes(pool: Pool, gid: int, pid: int) -> [Record]:
	"""Get the voting results in the form of (item id, vote counts, description)."""
	async with pool.acquire() as con:
		return await con.fetch(
			"""
			SELECT vote.iid, vote.count, item.description
			FROM poll_vote as vote
			INNER JOIN poll_item AS item ON vote.iid = item.id AND vote.pid = item.pid
			WHERE vote.gid = $1 AND vote.pid = $2
			""",
			gid, pid
		)


# async def get_counters(pool: Pool, gid: int) -> [int]:
# 	async with pool.acquire() as con:
# 		return await con.fetch(
# 			"""
# 			SELECT mid, count
# 			FROM counter
# 			WHERE gid = $1
# 			""",
# 			gid
# 		)

# async def update_count(pool:Pool, mid: int, count: int):
# 	async with pool.acquire() as con:
# 		async with con.transaction():
# 			await con.execute(
# 				"""
# 				UPDATE counter
# 				SET count = $2
# 				WHERE mid = $1
# 				""",
# 				mid, count
# 			)
