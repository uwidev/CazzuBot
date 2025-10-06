"""Tasks which are tied to the quarterly seasons are to be put here."""

import datetime
import logging
from typing import TYPE_CHECKING

import pendulum
from discord.ext import commands, tasks

from main import CazzuBot
from src import db
from src.utility import month2season

if TYPE_CHECKING:
	from main import CazzuBot

_log = logging.getLogger(__name__)


# def get_next_quarter(
# 	today: datetime.datetime | None = None,
# ) -> datetime.datetime:
# 	if today is None:
# 		today = datetime.datetime.today().astimezone(datetime.timezone.utc)
#
# 	quarters = [1, 4, 7, 10]
#
# 	for m in quarters:
# 		quarter_date = datetime.datetime(
# 			today.year, m, 1, tzinfo=datetime.timezone.utc
# 		)
# 		print(repr(today), repr(quarter_date))
# 		if quarter_date > today:
# 			return quarter_date
#
# 	return datetime.datetime(
# 		today.year + 1, 1, 1, tzinfo=datetime.timezone.utc
# 	)


# Used as a proxy to check quarterly
DAILY_RESET = datetime.time(0, tzinfo=datetime.timezone.utc)


class Quarterly(commands.Cog):
	def __init__(self, bot: CazzuBot, force_reset: bool = False):  # noqa: FBT002, FBT001
		"""Start tasks here."""
		self.bot = bot
		self.force_reset = force_reset

		self.quarterly_reset.start()

	async def cog_load(self):
		if self.force_reset:
			await self.reset()
			self.force_reset = False

	async def cog_unload(self):
		"""Cancel any tasks on unload."""
		self.quarterly_reset.cancel()

	@tasks.loop(time=DAILY_RESET)
	async def quarterly_reset(self):
		"""Dummy function to decorate for tasks."""  # noqa: D401
		last_quarterly: datetime.datetime = db.internal.get_last_quarterly(
			self.bot.pool
		)
		last_quarterly: int = month2season(last_quarterly.month)

		today: datetime.datetime = datetime.datetime.today().astimezone(
			datetime.timezone.utc
		)
		this_quarter: int = month2season(today.month)

		if not last_quarterly or this_quarter > last_quarterly:
			await self.reset()

	async def reset(self):
		"""Reset dailies."""
		_log.info("Running quarterly reset")

		db.member_frog.freeze_frogs(self.bot.pool)

		# Log the time this quarterly reset was done
		now = pendulum.now("UTC")
		await db.internal.set_last_quarterly(self.bot.pool, now)


async def setup(bot: CazzuBot):
	# Check when the last time quarterly resets were ran.
	# This is because if it's been +24 since the last reset,
	# we need to reset to accomodate the previous quarterly.
	now = pendulum.now("UTC")
	force_reset = False

	last_quarterly_raw: datetime.datetime = (
		await db.internal.get_last_quarterly(bot.pool)
	)
	# Bot has never resetted quarterlies before, or db fucked
	if not last_quarterly_raw:
		_log.warning(
			"There was no last time since the bot has done quarterly resets..."
		)
		force_reset = True
	else:
		# last_quarterly = pendulum.parser.parse(last_quarterly_raw)
		last_quarterly = datetime.datetime.fromisoformat(last_quarterly_raw)
		if month2season(now.month) > month2season(last_quarterly.month):
			force_reset = True

	await bot.add_cog(Quarterly(bot, force_reset=force_reset))
