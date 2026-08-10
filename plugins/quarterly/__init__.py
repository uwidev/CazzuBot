"""Quarterly plugin — freezes frogs at the season rollover.

The first instant of each quarter (Jan/Apr/Jul/Oct 1st 00:00 UTC) is a
quarterly cadence; every fire freezes all normal frogs (idempotent) and
re-arms the next quarter. The cadence itself encodes the season boundary,
so no last-freeze marker is needed — a bot down over the boundary fires
the overdue row on boot and freezes late.
"""

import logging

import pendulum

from cazzubot import Plugin
from cazzubot.bot import CazzuBot
from cazzubot.scheduler import At
from typing_extensions import override

from plugins.frogs import db as frog_db

_log = logging.getLogger(__name__)

# the season rollover: first instant of Jan/Apr/Jul/Oct
CADENCE = At(day=1, months=(1, 4, 7, 10), time="00:00")


async def reset(bot: CazzuBot) -> None:
    _log.info("Running quarterly reset — freezing frogs")
    await frog_db.freeze_frogs(bot.db)


async def on_quarterly_due(
    bot: CazzuBot, _payload: dict[str, object]
) -> None:
    """Scheduler handler for tag ``quarterly`` — freeze, then re-arm.

    Every fire is a season rollover by construction, so the freeze is
    unconditional (and idempotent). Re-arming last keeps the fired row
    live while the freeze runs, so a failed freeze is retried by the
    scheduler's retry policy.
    """
    await reset(bot)
    # re-arm: drop stale rows, schedule the next season start
    await bot.scheduler.drop_tag("quarterly")
    await bot.scheduler.add(
        "quarterly", CADENCE.next_run(pendulum.now("UTC")), {"retry": True}
    )


class QuarterlyPlugin(Plugin):
    name = "quarterly"
    scheduled = {"quarterly": on_quarterly_due}
    # the quarterly freeze lives in the frogs tables
    depends_on = ("frogs",)

    @override
    async def on_load(self, bot: CazzuBot) -> None:
        """Arm the quarterly cadence — but never clobber an existing row.

        A row left from a previous run is either future (armed) or
        overdue (bot was down over a season boundary — the scheduler
        fires it on boot and the freeze runs then). Only a rowless
        install needs a fresh arm.
        """
        if not await bot.scheduler.get("quarterly"):
            await bot.scheduler.drop_tag("quarterly")
            await bot.scheduler.add(
                "quarterly",
                CADENCE.next_run(pendulum.now("UTC")),
                {"retry": True},
            )


plugin = QuarterlyPlugin()
