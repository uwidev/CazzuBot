"""Manages everything related to logging frog captures.

Similar to member_frog_log, we partition by gid and index by date.
"""

import logging

import pendulum
from asyncpg import Pool

from . import table, utility

_log = logging.getLogger(__name__)


@utility.fkey_member
async def add(pool: Pool, payload: table.MemberFrogLog) -> None:
	"""Log frog capture."""
	# await create_partition(pool, payload.gid)

	async with pool.acquire() as con:
		async with con.transaction():
			await con.execute(
				"""
				INSERT INTO member_frog_log (gid, uid, type, at, waited_for)
				VALUES ($1, $2, $3, $4, $5)
				""",
				*payload,
			)


# async def create_partition(pool: Pool, gid: int) -> None:
#	  """Partition member frog log as needed."""
#	  now = pendulum.now()
#	  start = pendulum.datetime(now.year, now.month, 1)
#	  end = start.add(months=1)

#	  await create_partition_monthly(pool, start, end)
#	  await create_index_on_date(pool, start)


# async def create_partition_monthly(
#	  pool: Pool, start: pendulum.DateTime, end: pendulum.DateTime
# ) -> None:
#	  """Parition the frog capture log database by this month.

#	  Only creates the parition if it doesn't yet exist.
#	  """
#	  start_str = f"{start.year}_{start.month}"

#	  async with pool.acquire() as con:
#		  async with con.transaction():
#			  with contextlib.suppress(InvalidObjectDefinitionError):  # Already exists
#				  await con.execute(
#					  f"""
#					  CREATE TABLE IF NOT EXISTS frog_log_{start_str}
#						  PARTITION OF member_frog_log
#						  FOR VALUES FROM ('{start.to_date_string()}') TO ('{end.to_date_string()}')
#					  ;
#					  """
#				  )


# async def create_index_on_date(pool: Pool, date: pendulum.DateTime) -> None:
#	  """Index the selected partition."""
#	  start_str = f"{date.year}_{date.month}"

#	  async with pool.acquire() as con:
#		  async with con.transaction():
#			  await con.execute(
#				  f"""
#				  CREATE INDEX IF NOT EXISTS idx_frog_log_{start_str}
#				  ON frog_log_{start_str} (gid, uid)
#				  """
#			  )


async def get_monthly(
	pool: Pool, gid: int, uid: int, year: int, month: int
) -> int:
	"""Fetch a member's frog captures from the specified month.

	!! CURRENTLY DOES NOT DISCRIMINIATE BETWEEN FROG TYPES !!
	"""
	date = pendulum.datetime(year, month, 1)
	date_end = date.add(months=3)
	date_str = f"{date.year}_{date.month}"

	async with pool.acquire() as con:
		return await con.fetchval(
			f"""
			SELECT count(*)
			FROM member_frog_log
			WHERE gid = $1 AND uid = $2 AND at BETWEEN {date} AND {date_end}
			""",
			gid,
			uid,
		)


async def get_seasonal_by_month(
	pool: Pool, gid: int, uid: int, year: int, month: int
) -> int:
	"""Fetch a member's count seasonal frog captures by month.

	Passed argument should still be natural counting, starting from 1.

	For the month to bucket into seasons, it must be zero indexed for floor division.
	0-2  -> 0
	3-5  -> 1
	6-8  -> 2
	9-11 -> 3

	!! CURRENTLY DOES NOT DISCRIMINIATE BETWEEN FROG TYPES !!
	"""
	zero_indexed_month = month - 1
	return await get_seasonal(
		pool, gid, uid, year, zero_indexed_month // 3
	)


async def get_seasonal(
	pool: Pool, gid: int, uid: int, year: int, season: int
) -> int:
	"""Fetch a member's frog captures based on season.

	Seasons start from 0 and go to to 3.

	!! CURRENTLY DOES NOT DISCRIMINIATE BETWEEN FROG TYPES !!
	"""
	if season < 0 or season > 3:  # noqa: PLR2004
		msg = "Seasons must be in the range of 0-3"
		_log.error(msg)
		raise ValueError(msg)

	start_month = 1 + 3 * season  # season months start 1 4 7 10
	interval = [pendulum.datetime(year, start_month, 1)]
	interval.append(
		interval[0] + pendulum.duration(months=3)
	)  # [from, to]

	async with pool.acquire() as con:
		return await con.fetchval(
			"""
			SELECT COUNT(*)
			FROM member_frog_log
			WHERE gid = $1 AND uid = $2 AND at BETWEEN $3 AND $4
			""",
			gid,
			uid,
			interval[0],
			interval[1],
		)


async def get_seasonal_bulk_ranked(
	pool: Pool, gid: int, year: int, season: int
) -> int:
	"""Fetch frog captures and ranks them of a guild's members.

	Seasons start from 0 and go to to 3.

	Return records are 'formatted' as records [[rank, uid, count]]
	"""
	if season < 0 or season > 3:  # noqa: PLR2004
		msg = "Seasons must be in the range of 0-3"
		_log.error(msg)
		raise ValueError(msg)

	start_month = 1 + 3 * season  # season months start 1 4 7 10
	interval = [pendulum.datetime(year, start_month, 1)]
	interval.append(
		interval[0] + pendulum.duration(months=3)
	)  # [from, to]

	async with pool.acquire() as con:
		return await con.fetch(
			"""
			SELECT RANK() OVER (ORDER BY capture_count DESC) AS rank, uid, capture_count
			FROM (
				SELECT uid, COUNT(*) AS capture_count
				FROM member_frog_log
				WHERE gid = $1 AND at BETWEEN $2 AND $3
				GROUP BY uid
			) AS subquery
			ORDER BY capture_count DESC;
			""",
			gid,
			interval[0],
			interval[1],
		)


async def get_seasonal_total_members(
	pool: Pool, gid: int, year: int, season: int
) -> int:
	"""Return the count of all participants this season."""
	if season < 0 or season > 3:  # noqa: PLR2004
		msg = "Seasons must be in the range of 0-3"
		_log.error(msg)
		raise ValueError(msg)

	start_month = 1 + 3 * season  # season months start 1 4 7 10
	interval = [pendulum.datetime(year, start_month, 1)]
	interval.append(
		interval[0] + pendulum.duration(months=3)
	)  # [from, to]

	async with pool.acquire() as con:
		return await con.fetchval(
			"""
			SELECT COUNT(*)
			FROM (
				SELECT DISTINCT uid
				FROM member_frog_log
				WHERE gid = $1 AND at BETWEEN $2 AND $3
			)
			""",
			gid,
			interval[0],
			interval[1],
		)


async def get_seasonal_total_members_by_month(
	pool: Pool, gid: int, year: int, month: int
) -> int:
	zero_indexed_month = month - 1
	return await get_seasonal_total_members(
		pool, gid, year, zero_indexed_month // 3
	)


async def get_total_members(
	pool: Pool,
	gid: int,
) -> int:
	async with pool.acquire() as con:
		return await con.fetchval(
			"""
			SELECT COUNT(*)
			FROM member_frog
			WHERE gid = $1
			""",
			gid,
		)
