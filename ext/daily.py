"""Tasks which are tied to the bot's daily life cycles are to be put here."""

import asyncio
import datetime
import logging

import pendulum
from discord.ext import commands, tasks

from src.db import internal, member


_log = logging.getLogger(__name__)

DAILY_RESET = datetime.time(0, tzinfo=datetime.timezone.utc)


class Daily(commands.Cog):
    def __init__(self, bot, force_reset: bool = False):  # noqa: FBT002, FBT001
        """Start tasks here."""
        self.bot = bot
        self.force_reset = force_reset

        self.daily_reset.start()

    async def cog_load(self):
        if self.force_reset:
            await self.reset()
            self.daily_reset = False

    async def cog_unload(self):
        """Cancel any tasks on unload."""
        self.daily_reset.cancel()

    @tasks.loop(time=DAILY_RESET)
    async def daily_reset(self):
        """Dummy function to decorate for tasks."""  # noqa: D401
        await self.reset()

    async def reset(self):
        """Reset dailies."""
        _log.info("Running daily reset")

        # Reset all message counts and cdr
        await member.reset_all_msg_cnt(self.bot.pool)
        await member.reset_all_cdr(self.bot.pool)

        # Log the time this daily reset was done
        now = pendulum.now("UTC")
        this_daily = now.set(hour=0, minute=0, second=0, microsecond=0)
        await internal.set_last_daily(self.bot.pool, str(this_daily))


async def setup(bot: commands.Bot):
    # Check when the last time daily resets were ran.
    # This is because if it's been +24 since the last reset,
    # we need to reset to accomodate the previous daily.
    now = pendulum.now("UTC")

    last_daily_raw = await internal.get_last_daily(bot.pool)
    last_daily = pendulum.parser.parse(last_daily_raw)
    _log.info(f"{now=}")
    _log.info(f"{last_daily=}")

    force_reset = False

    if not last_daily:  # Bot has never resetted dailies before, or db fucked
        _log.warning("There was no last time since the bot has done daily resets...")

    if not last_daily or now > last_daily + pendulum.duration(days=1):
        force_reset = True

    await bot.add_cog(Daily(bot, force_reset=force_reset))
