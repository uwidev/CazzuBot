"""Daily plugin — resets message counts and cooldowns at 00:00 UTC.

Port of v1's ``ext/daily.py``. The daily reset is remembered in settings so a
bot that was down at midnight still runs the reset on boot; the midnight
cadence is re-armed through the central scheduler (tag ``daily``).
"""

import logging

import pendulum

from cazzubot import Plugin, utils
from cazzubot.bot import CazzuBot
from cazzubot.timeparse import parse_iso8601
from typing_extensions import override

from plugins.experience import db as exp_db
from plugins.frogs import db as frog_db

_log = logging.getLogger(__name__)

LAST_KEY = "daily.last_daily"


async def reset(bot: CazzuBot) -> None:
    """Daily reset: msg counts back to 1, cooldowns cleared, resync."""
    _log.info("Running daily reset")
    await exp_db.reset_all_msg_cnt(bot.db)
    await exp_db.reset_all_cdr(bot.db)
    await exp_db.sync_with_exp_logs(bot.db)
    await frog_db.sync_with_frog_logs(bot.db)
    await bot.settings.set(LAST_KEY, pendulum.now("UTC"))


async def on_daily_due(bot: CazzuBot, _payload: dict[str, object]) -> None:
    """Scheduler handler for tag ``daily`` — re-arm, then reset if due."""
    await utils.arm_midnight_cadence(bot, "daily")
    last: str | None = await bot.settings.get(LAST_KEY)
    now = pendulum.now("UTC")
    if last is None or parse_iso8601(last) < now.subtract(hours=24):
        await reset(bot)


class DailyPlugin(Plugin):
    name = "daily"
    scheduled = {"daily": on_daily_due}

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Run a missed daily reset (bot was down at midnight)."""
        last = await bot.settings.get(LAST_KEY)
        now = pendulum.now("UTC")
        if last is None or parse_iso8601(last) < now.subtract(hours=24):
            _log.warning(
                "daily reset was missed (last: %r); forcing now", last
            )
            await reset(bot)
        # re-arm the midnight cadence (drop stale rows first)
        await utils.arm_midnight_cadence(bot, "daily")


plugin = DailyPlugin()
