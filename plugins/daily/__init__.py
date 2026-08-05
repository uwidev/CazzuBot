"""Daily plugin — resets message counts and cooldowns at 00:00 UTC.

Port of v1's ``ext/daily.py``. The daily reset is remembered in settings so a
bot that was down at midnight still runs the reset on boot.
"""

import datetime
import logging

import pendulum
from discord.ext import commands, tasks

from cazzubot import Plugin

from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db

_log = logging.getLogger(__name__)

RESET_TIME = datetime.time(0, tzinfo=datetime.timezone.utc)
LAST_KEY = "daily.last_daily"


class DailyCog(commands.Cog):
	"""Daily exp/frog resets."""

	def __init__(self, bot, *, force_reset: bool = False) -> None:
		self.bot = bot
		self.force_reset = force_reset
		self.daily_reset.start()

	async def cog_load(self) -> None:
		if self.force_reset:
			await self.reset()
			self.force_reset = False

	async def cog_unload(self) -> None:
		self.daily_reset.cancel()

	@tasks.loop(time=RESET_TIME)
	async def daily_reset(self) -> None:
		last: str | None = await self.bot.settings.get(LAST_KEY)
		now = pendulum.now("UTC")
		if last is None or pendulum.parse(last) < now.subtract(hours=24):
			await self.reset()

	async def reset(self) -> None:
		"""Daily reset: msg counts back to 1, cooldowns cleared, resync."""
		_log.info("Running daily reset")
		await exp_db.reset_all_msg_cnt(self.bot.db)
		await exp_db.reset_all_cdr(self.bot.db)
		await exp_db.sync_with_exp_logs(self.bot.db)
		await frog_db.sync_with_frog_logs(self.bot.db)
		await self.bot.settings.set(LAST_KEY, pendulum.now("UTC"))


class DailyPlugin(Plugin):
	name = "daily"
	cogs = [DailyCog]

	async def on_load(self, bot) -> None:
		"""Run a missed daily reset (bot was down at midnight)."""
		last = await bot.settings.get(LAST_KEY)
		now = pendulum.now("UTC")
		if last is None or pendulum.parse(last) < now.subtract(hours=24):
			_log.warning(
				"daily reset was missed (last: %r); forcing now", last
			)
			cog = bot.get_cog("DailyCog")
			if cog is not None:
				await cog.reset()


plugin = DailyPlugin()
