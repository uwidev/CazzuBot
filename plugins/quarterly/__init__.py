"""Quarterly plugin — freezes frogs when the season rolls over.

Port of v1's ``ext/quarterly.py``. Checks daily at 00:00 UTC (re-armed
through the central scheduler, tag ``quarterly``); when the quarter index
increases, all normal frogs become frozen frogs.
"""

import logging

import pendulum

from cazzubot import Plugin, utils
from cazzubot.bot import CazzuBot
from cazzubot.scheduler import Cadence
from cazzubot.timeparse import parse_iso8601
from typing_extensions import override

from plugins.frogs import db as frog_db

_log = logging.getLogger(__name__)

LAST_KEY = "quarterly.last_quarterly"

# checked once a day at 00:00 UTC — armed by on_quarterly_due and on_load
CADENCE = Cadence(time="00:00")


async def reset(bot: CazzuBot) -> None:
    _log.info("Running quarterly reset — freezing frogs")
    await frog_db.freeze_frogs(bot.db)
    await bot.settings.set(LAST_KEY, pendulum.now("UTC"))


async def on_quarterly_due(
    bot: CazzuBot, _payload: dict[str, object]
) -> None:
    """Scheduler handler for tag ``quarterly`` — check, then freeze."""
    await bot.scheduler.arm("quarterly", CADENCE)
    last_raw = await bot.settings.get(LAST_KEY)
    now = pendulum.now("UTC")
    if last_raw:
        last = parse_iso8601(last_raw)
        last_quarter = (last.year, utils.month2season(last.month))
    else:
        last_quarter = (-1, -1)
    this_quarter = (now.year, utils.month2season(now.month))
    if this_quarter > last_quarter:
        await reset(bot)


class QuarterlyPlugin(Plugin):
    name = "quarterly"
    scheduled = {"quarterly": on_quarterly_due}
    # the quarterly freeze lives in the frogs tables
    depends_on = ("frogs",)

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Freeze frogs if the quarter rolled over while the bot was down."""
        last_raw = await bot.settings.get(LAST_KEY)
        force = False
        if last_raw is None:
            _log.warning(
                "no record of the last quarterly reset; forcing one"
            )
            force = True
        elif (
            pendulum.now("UTC").year,
            utils.month2season(pendulum.now("UTC").month),
        ) > (
            parse_iso8601(last_raw).year,
            utils.month2season(parse_iso8601(last_raw).month),
        ):
            force = True

        if force:
            await reset(bot)
        # re-arm the midnight cadence (drop stale rows first)
        await bot.scheduler.arm("quarterly", CADENCE)


plugin = QuarterlyPlugin()
